# -*- coding: utf-8 -*-
"""
Supremacy 1914 — 每日自動化腳本（由 Windows 工作排程器於 automation.json 設定的時間觸發）。

流程：
  1. 重試連線遊戲分頁並擷取，直到確認「遊戲日真的推進到新的一天」才提交
     （預設每 10 分重試、窗口 4 小時，皆可在 automation.json 調整）。
     —— 遊戲分頁必須開著才能經 CDP 讀取資料，關閉時天然無法擷取，
        故採「固定鐘點排程 + 有限重試」而非 24h 全天候輪詢。
     —— 不依賴精確切日鐘點：即使排程早/晚幾小時，只要在窗口內偵測到 day 遞增就提交。
  2. 擷取成功且遊戲日遞增後，由 extract_day.py 自動重建儀表盤。
  3. 提交並推送 main；GitHub Actions 偵測 push 後自動部署到 gh-pages。
  4. 若 automation.json 的排程時間與現有工作排程不同，重新註冊（使用者改時間後重跑 setup 即生效）。

前置：setup_automation.py 已執行過一次（註冊排程 + 設定 git 憑證）。
"""
import os
import sys
import json
import time
import glob
import subprocess
import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
VENV_PY = r"C:\Users\acer\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
EXTRACT = os.path.join(BASE, "extract_day.py")

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


CONFIG_PATH = os.path.join(BASE, "automation.json")


def load_config():
    cfg = {"scheduleTime": "17:05", "retryMinutes": 10, "retryWindowHours": 4}
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def max_day_in_games():
    """回傳所有對局中最大的遊戲日，用於判斷是否真的切到新的一天。"""
    best = 0
    for fp in glob.glob(os.path.join(BASE, "games", "*", "data", "day_*.json")):
        try:
            d = json.load(open(fp, encoding="utf-8"))
            day = d.get("day")
            if isinstance(day, int) and day > best:
                best = day
        except Exception:
            pass
    return best


def log(m):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {m}", flush=True)


def run_extract():
    try:
        r = subprocess.run([VENV_PY, EXTRACT], cwd=BASE)
        return r.returncode == 0
    except Exception as e:
        log(f"擷取例外：{e}")
        return False


def git(*args):
    return subprocess.run(["git", *args], cwd=BASE, capture_output=True, text=True)


def reregister_if_needed():
    """若 automation.json 的排程時間與現有工作排程不同，重新註冊（使用者改時間後重跑 setup 即生效）。"""
    try:
        cfg = load_config()
        st = cfg.get("scheduleTime", "17:05")
        out = subprocess.run(["schtasks", "/Query", "/TN", "Supremacy1914Daily", "/FO", "LIST"],
                             capture_output=True, text=True)
        cur = None
        for line in out.stdout.splitlines():
            if "Start Time" in line:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    cur = parts[1].strip()[-5:]  # HH:MM
        if cur and cur != st:
            subprocess.run(["schtasks", "/Create", "/TN", "Supremacy1914Daily",
                            "/TR", f'cmd /c "{os.path.join(BASE, "runner.bat")}"',
                            "/SC", "DAILY", "/ST", st, "/F"], capture_output=True, text=True)
            log(f"偵測到 automation.json 排程時間 {st} 與現有 {cur} 不同，已重註冊排程。")
    except Exception as e:
        log(f"排程重註冊檢查失敗（可忽略）：{e}")


def main():
    cfg = load_config()
    retry_min = int(cfg.get("retryMinutes", 10))
    window_h = float(cfg.get("retryWindowHours", 4))
    deadline = time.time() + window_h * 3600
    prev_day = max_day_in_games()
    log(f"上次遊戲日 = {prev_day or '未知'}；開始擷取（每 {retry_min} 分重試，窗口 {window_h}h）…")
    advanced = False
    while time.time() < deadline:
        if run_extract():
            new_day = max_day_in_games()
            if prev_day and new_day > prev_day:
                advanced = True
                log(f"偵測到遊戲日推進 {prev_day} → {new_day}，準備提交。")
                break
            if new_day == prev_day:
                log(f"遊戲日仍為 {new_day}（尚未切到新的一天），{retry_min} 分後重試…")
            else:
                advanced = True
                log(f"遊戲日 = {new_day}，準備提交。")
                break
        else:
            log(f"遊戲分頁尚未就緒，{retry_min} 分後重試…")
        time.sleep(retry_min * 60)
    if not advanced:
        log("窗口內皆未取得新的一天，今日跳過（明日排程再試）。")
        sys.exit(2)

    reregister_if_needed()

    # git 提交並推送（GitHub Actions 會自動部署）
    git("add", "games/", "supremacy1914_dashboard.html")
    d = git("diff", "--cached", "--quiet")
    if d.returncode != 0:
        day = None
        files = sorted(glob.glob(os.path.join(BASE, "games", "*", "data", "day_*.json")))
        if files:
            try:
                last = json.load(open(files[-1], encoding="utf-8"))
                day = last.get("day")
            except Exception:
                pass
        msg = f"auto: 遊戲日 {day} 快照與儀表盤更新" if day else "auto: 資料更新"
        git("commit", "-m", msg)
        p = git("push", "origin", "main")
        if p.returncode != 0:
            log(f"推送失敗：{p.stderr}")
            sys.exit(3)
        log("已推送 main，GitHub Actions 將自動部署到 gh-pages。")
    else:
        log("無變更，跳過提交。")


if __name__ == "__main__":
    main()
