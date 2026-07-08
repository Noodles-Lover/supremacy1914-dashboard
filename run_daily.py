# -*- coding: utf-8 -*-
"""
Supremacy 1914 — 每日自動化腳本（由 Windows 工作排程器於「切日鐘點 + 5 分」觸發）。

流程：
  1. 重試連線遊戲分頁（最長 2 小時，每 15 分鐘一次），直到擷取成功。
     —— 遊戲分頁必須開著才能經 CDP 讀取資料，關閉時天然無法擷取，
        故採「固定鐘點排程 + 有限重試」而非 24h 全天候輪詢。
  2. 擷取成功後由 extract_day.py 自動重建儀表盤。
  3. 提交並推送 main；GitHub Actions 偵測 push 後自動部署到 gh-pages。
  4. 檢查新對局的切日鐘點是否與現有排程不同，必要時重註冊工作排程。

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
    """若新對局的切日鐘點與現有排程不同，重新註冊工作排程（換對局時自動校正）。"""
    try:
        games_dir = os.path.join(BASE, "games")
        meta_paths = []
        for gid in os.listdir(games_dir):
            mp = os.path.join(games_dir, gid, "meta.json")
            if os.path.exists(mp):
                meta_paths.append(mp)
        if not meta_paths:
            return
        latest = max(meta_paths, key=os.path.getmtime)
        meta = json.load(open(latest, encoding="utf-8"))
        sc = meta.get("switchClock")
        if not sc:
            return
        out = subprocess.run(["schtasks", "/Query", "/TN", "Supremacy1914Daily", "/FO", "LIST"],
                             capture_output=True, text=True)
        cur = None
        for line in out.stdout.splitlines():
            if "起始時間" in line or "Start Time" in line:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    cur = parts[1].strip()[-5:]  # HH:MM
        if cur and cur != sc:
            st = (datetime.datetime.strptime(sc, "%H:%M") + datetime.timedelta(minutes=5)).strftime("%H:%M")
            subprocess.run(["schtasks", "/Create", "/TN", "Supremacy1914Daily",
                            "/TR", f'cmd /c "{os.path.join(BASE, "runner.bat")}"',
                            "/SC", "DAILY", "/ST", st, "/F"], capture_output=True, text=True)
            log(f"偵測到新對局切日鐘點 {sc}，已重註冊排程為 {st}。")
    except Exception as e:
        log(f"排程重註冊檢查失敗（可忽略）：{e}")


def main():
    deadline = time.time() + 2 * 3600  # 2 小時重試窗口
    ok = False
    while time.time() < deadline:
        if run_extract():
            ok = True
            break
        log("遊戲分頁尚未就緒，15 分鐘後重試…")
        time.sleep(15 * 60)
    if not ok:
        log("2 小時內皆無法連上遊戲分頁，今日跳過（明日排程再試）。")
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
