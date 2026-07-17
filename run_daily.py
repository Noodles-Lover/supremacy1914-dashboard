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
  3. 直接部署到 gh-pages（deploy_ghpages.py 用 git worktree 推送），main 不動、不會每天多 commit。
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
# 使用啟動本腳本的直譯器（自動跟隨 runner.bat 或手動執行時所用的 python），
# 避免硬編碼 venv 路徑在被 WorkBuddy 清理後導致 [WinError 2]。
# 註：排程由 runner.bat 確保用含 websockets 的 venv 啟動，故 sys.executable 必含依賴。
VENV_PY = sys.executable
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
            # 複用 setup_automation 的健壯 XML 註冊，避免重建出脆弱任務
            try:
                import setup_automation
                setup_automation.register_task(st)
                log(f"偵測到 automation.json 排程時間 {st} 與現有 {cur} 不同，已用健壯設定重註冊排程。")
            except Exception as e:
                log(f"排程重註冊失敗（可忽略，下次手動跑 setup_automation.py 即可）：{e}")
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

    # 重建儀表盤已由 extract_day.py（當日首次報告）完成；直接部署到 gh-pages。
    # 不提交 main，因此 main 不會每天多一個 commit。
    DEPLOY = os.path.join(BASE, "deploy_ghpages.py")
    if not os.path.exists(DEPLOY):
        log("[WARN] 找不到 deploy_ghpages.py，跳過自動部署。")
    else:
        log("[..] 部署到 gh-pages…")
        try:
            r = subprocess.run([VENV_PY, DEPLOY], cwd=BASE)
            if r.returncode != 0:
                log(f"部署失敗（exit {r.returncode}），請檢查 git 憑證/網路。")
                sys.exit(3)
        except Exception as e:
            log(f"部署例外：{e}")
            sys.exit(3)
        log("已推送 gh-pages，站點將更新。main 未因此產生每日 commit。")


if __name__ == "__main__":
    main()
