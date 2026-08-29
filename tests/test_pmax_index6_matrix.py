"""
Approved APP-20260829-001-PMAX6DEV 單元測試：calc_pmax_index6_matrix 邏輯
為避免 import streamlit app.py 模塊時觸發 st.set_page_config，本檔重現純函數邏輯 + 常量
並用 synthetic df 覆蓋 6 個 Quality Gate：
  TC1 Pmax 正確
  TC2 2 點 Pm * Index 抽查（0.625 / 0.125）
  TC3 P_Avg3 前 2 日 NaN（min_periods=3）
  TC4 Dev0 符號：Close[t] > Avg3[t] → 正
  TC5 Dev5 越界：第 0~4 日 → NaN
  TC6 紅框自動校準：強構 2026-08-11 的 Dev2=+3.5197，驗證 cal_match.值正確
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# --- APPROVED M2 強制硬編碼 20 Index（與 app.py / app_mobile.py 一致）---
PMAX_20_FIXED_INDICES = [
    0.625, 0.583, 0.542, 0.500, 0.458, 0.417, 0.396, 0.375, 0.354, 0.333,
    0.313, 0.292, 0.271, 0.250, 0.229, 0.208, 0.188, 0.167, 0.146, 0.125,
]
CAL_TARGET_RED_VALUE = 3.5197


def calc_pmax_index6_matrix(df: pd.DataFrame,
                            pmax_window: int = 106,
                            avg_window: int = 3,
                            dev_offsets=None,
                            recent_rows: int = 12):
    dev_offsets = dev_offsets if dev_offsets is not None else [0, 1, 2, 3, 4, 5]
    res = {
        "ok": False, "reason": "", "pm": None, "pm_window": pmax_window,
        "index_rows": [], "time_rows": [],
        "dev_offsets": list(dev_offsets),
        "cal_match": {"date": None, "k": None, "value": None, "abs_err": None},
    }
    if df is None or df.empty:
        res["reason"] = "df empty"
        return res
    try:
        work = df.copy()
        if "Close" not in work.columns:
            res["reason"] = "missing Close column"
            return res
        work["_close"] = pd.to_numeric(work["Close"], errors="coerce")
        if "High" in work.columns:
            work["_hi"] = pd.to_numeric(work["High"], errors="coerce")
            hi_series = work["_hi"]
        else:
            hi_series = work["_close"]
        if "Turnover_Rate" in work.columns:
            work["_tur"] = pd.to_numeric(work["Turnover_Rate"], errors="coerce")
        else:
            work["_tur"] = pd.Series([np.nan] * len(work), index=work.index)
        if "AMP" in work.columns:
            work["_amp"] = pd.to_numeric(work["AMP"], errors="coerce")
        elif "High" in work.columns and "Low" in work.columns and "Close" in work.columns:
            prev_close = work["_close"].shift(1).replace(0, np.nan)
            hi = pd.to_numeric(work["High"], errors="coerce")
            lo = pd.to_numeric(work["Low"], errors="coerce")
            work["_amp"] = (hi - lo) / prev_close * 100.0
        else:
            work["_amp"] = pd.Series([np.nan] * len(work), index=work.index)

        top = min(len(work), pmax_window)
        if top < 30:
            res["reason"] = f"僅 {len(work)} 列，不足 Pmax({pmax_window}) 最低 30"
            return res
        recent_pmax = work.tail(top)
        combined = pd.concat([
            recent_pmax["_close"].replace(0, np.nan),
            hi_series.tail(top).replace(0, np.nan),
        ], axis=1)
        daily_max = combined.max(axis=1, skipna=True).dropna()
        if daily_max.empty:
            res["reason"] = "無法計算 Pmax"
            return res
        Pm = float(daily_max.max())
        if not np.isfinite(Pm) or Pm <= 0:
            res["reason"] = f"Pm={Pm} 非合理正數"
            return res
        res["pm"] = Pm
        idx_rows = []
        for i, v in enumerate(PMAX_20_FIXED_INDICES):
            idx_rows.append({"idx": i, "index": float(v), "pm_x_index": float(Pm * float(v))})
        res["index_rows"] = idx_rows

        work["_avg3"] = work["_close"].rolling(window=avg_window, min_periods=avg_window).mean()
        dates = pd.to_datetime(work.index)
        T = len(work)
        pick_start = max(0, T - recent_rows)
        t_rows = []
        best_match = {"abs_err": float("inf")}
        for t in range(pick_start, T):
            date_s = dates[t].strftime("%Y-%m-%d") if pd.notna(dates[t]) else ""
            close_v = work["_close"].iloc[t]
            tur_v = work["_tur"].iloc[t]
            amp_v = work["_amp"].iloc[t]
            avg3_t = work["_avg3"].iloc[t]
            dev_dict = {}
            for k in dev_offsets:
                ref_t = t - int(k)
                if ref_t < 0:
                    dev_dict[int(k)] = float("nan")
                    continue
                avg3_ref = work["_avg3"].iloc[ref_t]
                if avg3_ref is None or pd.isna(avg3_ref) or float(avg3_ref) == 0 or not np.isfinite(float(avg3_ref)):
                    dev_dict[int(k)] = float("nan")
                    continue
                if close_v is None or pd.isna(close_v) or not np.isfinite(float(close_v)):
                    dev_dict[int(k)] = float("nan")
                    continue
                dev_dict[int(k)] = (float(close_v) - float(avg3_ref)) / float(avg3_ref) * 100.0
            for k, dv in dev_dict.items():
                if dv is None or (isinstance(dv, float) and not np.isfinite(dv)) or pd.isna(dv):
                    continue
                err = abs(float(dv) - CAL_TARGET_RED_VALUE)
                if err < best_match["abs_err"]:
                    best_match = {"date": date_s, "k": int(k), "value": float(dv), "abs_err": float(err)}
            t_rows.append({
                "date": date_s,
                "close": float(close_v) if (close_v is not None and pd.notna(close_v)) else None,
                "tur": (float(tur_v) if (tur_v is not None and pd.notna(tur_v) and np.isfinite(float(tur_v))) else None),
                "amp": (float(amp_v) if (amp_v is not None and pd.notna(amp_v) and np.isfinite(float(amp_v))) else None),
                "avg3_t": float(avg3_t) if (avg3_t is not None and pd.notna(avg3_t) and np.isfinite(float(avg3_t))) else None,
                "dev": dev_dict,
            })
        res["time_rows"] = t_rows
        if best_match.get("date") is not None:
            res["cal_match"] = best_match
        res["ok"] = True
        return res
    except Exception as exc:
        res["ok"] = False
        res["reason"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        return res


# ============================================================
# Fixture：Synthetic 150 天 Close，2026-03-17 ~ 2026-08-11（包含 8/11 做紅框校準）
# 規律：Close 從 100.0 線性漲到 141.1（在第 106 天達 141.1 = Pmax peak），最後 12 天構造 8/11
# ============================================================
def _build_synthetic_df(seed=42):
    np.random.seed(seed)
    N = 150
    dates = pd.bdate_range(end="2026-08-11", periods=N)  # 150 個交易日，最後一天=8/11
    # 線性漲幅：100 → 141.1，在 i=105 (0-indexed) 處達到 peak=141.1
    slope = (141.1 - 100.0) / 105.0
    close_arr = np.full(N, 100.0)
    for i in range(N):
        if i <= 105:
            close_arr[i] = 100.0 + slope * float(i)
        else:
            close_arr[i] = 141.1 - 0.25 * float(i - 105)  # 後 44 天緩跌
    # High = Close*1.015，Low=Close*0.985 → Amp 約 3%
    high_arr = close_arr * 1.015
    low_arr = close_arr * 0.985
    # Turnover_Rate 隨機 0.05 ~ 0.25
    tur_arr = np.random.uniform(0.05, 0.25, size=N)
    df = pd.DataFrame({
        "Open": close_arr * 0.998,
        "High": high_arr,
        "Low": low_arr,
        "Close": close_arr,
        "Volume": np.random.randint(5_000_000, 100_000_000, size=N),
        "Turnover_Rate": tur_arr,
    }, index=dates)

    # --- 重點：把最後 12 日中 8/11（最後一日）的 Close 做手動調整，使 Dev2 = Close[t] / Avg3[t−2] − 1 == +3.5197% * 100
    # 先讓 Avg3[t−2 for t=149] = (C[147]+C[148]+C[149_target])/3？不：
    #   Dev2[t] = (Close[t] - Avg3[t-2]) / Avg3[t-2] * 100
    #   Avg3[t-2=147] = (C[145]+C[146]+C[147])/3  => 先算原來的值
    C = close_arr.copy()
    avg3_147 = (C[145] + C[146] + C[147]) / 3.0
    target_dev = CAL_TARGET_RED_VALUE  # +3.5197
    # Dev2[t=149] = (Close[149] - avg3_147)/avg3_147*100 = target_dev
    desired_close_149 = avg3_147 * (1.0 + target_dev / 100.0)
    C[149] = desired_close_149
    df.loc[dates[149], "Close"] = desired_close_149
    # 相應調整 High/Low/Open，保持 Amp 一致
    df.loc[dates[149], "Open"] = desired_close_149 * 0.998
    df.loc[dates[149], "High"] = desired_close_149 * 1.015
    df.loc[dates[149], "Low"] = desired_close_149 * 0.985
    return df


def test_tc1_pmax_value_correct():
    """TC1：Pmax = 過去 106 日 max(daily max(Close, High)) = 141.1（合成時設定 i=105 為 peak）"""
    df = _build_synthetic_df()
    res = calc_pmax_index6_matrix(df, pmax_window=106, avg_window=3,
                                   dev_offsets=[0,1,2,3,4,5], recent_rows=12)
    assert res["ok"] is True, res["reason"]
    assert abs(float(res["pm"]) - 141.1) < 1e-6, f"Pmax={res['pm']} expected=141.1"


def test_tc2_pm_times_index_two_spots():
    """TC2：抽查 2 點 Pm*Index：i=0(0.625) → 88.1875；i=19(0.125) → 17.6375"""
    df = _build_synthetic_df()
    res = calc_pmax_index6_matrix(df, pmax_window=106, avg_window=3, recent_rows=12)
    assert res["ok"]
    idx_rows = res["index_rows"]
    assert len(idx_rows) == 20, f"len idx_rows={len(idx_rows)}"
    r0 = idx_rows[0]
    assert abs(float(r0["index"]) - 0.625) < 1e-9
    assert abs(float(r0["pm_x_index"]) - 88.1875) < 1e-3, f"r0.pm×Index={r0['pm_x_index']} expected=88.1875"
    r19 = idx_rows[19]
    assert abs(float(r19["index"]) - 0.125) < 1e-9
    assert abs(float(r19["pm_x_index"]) - 17.6375) < 1e-3, f"r19.pm×Index={r19['pm_x_index']} expected=17.6375"


def test_tc3_avg3_first_two_days_nan():
    """TC3：Avg3 前 2 日 (index 0, 1) 必然 NaN（min_periods=3）"""
    df = _build_synthetic_df()
    # 取整個 df 計算，再查 time_rows 以外的 Avg3：直接透過 rolling 檢查也可以
    # 這裡改為構造 tiny df=6 列，檢查 time_rows（取 recent_rows=6）第 0/1 列 avg3_t 應 NaN
    df_small = df.tail(6).copy()
    # 若 df_small 只有 6 列，Pmax window=106 會擋下（<30），所以用 mock：直接呼叫 calc 並把 df 長度降到 6，檢查 reason 就好？
    # 改用：傳遞 large df，檢查第一個 time_row 的前兩天不存在，而是檢查 df 的 _avg3.rolling 在開頭 NaN → 透過 calc 內部檢查：
    # calc 是黑盒，所以改 recent_rows=150，檢查 time_rows 的第 0, 1, 2 列：0,1→NaN，2→有效
    res = calc_pmax_index6_matrix(df, pmax_window=106, avg_window=3, recent_rows=150)
    assert res["ok"]
    tr = res["time_rows"]
    assert len(tr) == 150
    assert tr[0]["avg3_t"] is None or pd.isna(tr[0]["avg3_t"]), f"tr[0].avg3={tr[0]['avg3_t']} 應 NaN"
    assert tr[1]["avg3_t"] is None or pd.isna(tr[1]["avg3_t"]), f"tr[1].avg3={tr[1]['avg3_t']} 應 NaN"
    assert tr[2]["avg3_t"] is not None and pd.notna(tr[2]["avg3_t"]), f"tr[2].avg3={tr[2]['avg3_t']} 應有效"


def test_tc4_dev0_sign_positive_when_close_above_avg3():
    """TC4：Dev0[t] = (Close[t] - Avg3[t])/Avg3[t]*100 → Close>Av3 → 正"""
    df = _build_synthetic_df()
    res = calc_pmax_index6_matrix(df, pmax_window=106, avg_window=3, recent_rows=150)
    assert res["ok"]
    # i=105：peak=141.1，線性漲 -> Avg3[105] = (103+104+105 slope values)/3 < Close=141.1，必然正
    t = 105
    dev0 = res["time_rows"][t]["dev"].get(0)
    assert dev0 is not None and np.isfinite(float(dev0)), f"dev0={dev0} (t=105)"
    assert float(dev0) > 0.0, f"t=105 Dev0={dev0} 應正"


def test_tc5_dev5_out_of_bounds_first_rows_nan():
    """TC5：Dev5 越界：t=0..4 → t−5 <0 → Dev5 應 NaN"""
    df = _build_synthetic_df()
    res = calc_pmax_index6_matrix(df, pmax_window=106, avg_window=3, recent_rows=150)
    assert res["ok"]
    tr = res["time_rows"]
    for t in range(0, 5):
        d5 = tr[t]["dev"].get(5)
        assert d5 is None or pd.isna(d5) or not np.isfinite(float(d5)), \
            f"t={t} Dev5={d5} 應 NaN (越界 t-5<0)"
    # t=5 Dev5 應有效 (t-5=0 有 Avg3? No: Avg3[0] is NaN min_periods=3 → 仍 NaN)
    # t=7: t-5=2，Avg3[2] 剛好有效 → Dev5 應有效
    ok_t = None
    for t in range(5, 30):
        if tr[t]["dev"].get(5) is not None and np.isfinite(float(tr[t]["dev"][5])):
            ok_t = t
            break
    assert ok_t is not None, "t>=7 應存在 Dev5 有效值"


def test_tc6_calibration_redbox_35197():
    """TC6：紅框自動校準。合成 df 在 2026-08-11 Dev2=+3.5197，驗證 cal_match.date==2026-08-11 / k=2 / abs_err<1e-6"""
    df = _build_synthetic_df()
    res = calc_pmax_index6_matrix(df, pmax_window=106, avg_window=3, recent_rows=12)
    assert res["ok"]
    cm = res["cal_match"]
    assert cm.get("date") == "2026-08-11", f"cal_match.date={cm.get('date')} 應=2026-08-11"
    assert cm.get("k") == 2, f"cal_match.k={cm.get('k')} 應=2"
    assert abs(float(cm.get("abs_err", 999999))) < 1e-6, f"cal_match.abs_err={cm.get('abs_err')} 應<1e-6"
    assert abs(float(cm.get("value", -9999)) - CAL_TARGET_RED_VALUE) < 1e-6, \
        f"cal_match.value={cm.get('value')} 應={CAL_TARGET_RED_VALUE}"


if __name__ == "__main__":
    import traceback
    test_cases = [
        ("TC1 Pmax", test_tc1_pmax_value_correct),
        ("TC2 Pm*Index 抽查", test_tc2_pm_times_index_two_spots),
        ("TC3 Avg3 前2日 NaN", test_tc3_avg3_first_two_days_nan),
        ("TC4 Dev0 符號", test_tc4_dev0_sign_positive_when_close_above_avg3),
        ("TC5 Dev5 越界", test_tc5_dev5_out_of_bounds_first_rows_nan),
        ("TC6 紅框 3.5197", test_tc6_calibration_redbox_35197),
    ]
    ok = 0
    fail = 0
    for name, fn in test_cases:
        try:
            fn()
            print(f"✅ PASS {name}")
            ok += 1
        except AssertionError as e:
            print(f"❌ FAIL {name}: {e}")
            fail += 1
        except Exception as e:  # noqa: BLE001
            print(f"🔥 EXCEPTION {name}: {e}\n{traceback.format_exc()}")
            fail += 1
    print(f"\n===> {ok}/{len(test_cases)} passed, {fail} failed")
