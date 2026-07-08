# -*- coding: utf-8 -*-
"""
Supremacy 1914 — 一次性自動化設定（僅需執行一次）。

職責：
  1. 確保 games/{gameID}/meta.json 存在並含 switchClock（切日鐘點）。
     若遊戲分頁當下開著 → 即時擷取取得；否則用預設 17:00（遊戲開啟後重跑本腳本會自動校正）。
  2. 用 Windows 工作排程器（schtasks）註冊每日工作 Supremacy1914Daily，
     於「切日鐘點 + 5 分」執行 runner.bat（→ run_daily.py）。
  3. 若環境變數 GITHUB_PAT 已設定，將其寫入 git credential store，
     使每日推送 main 無需互動（GitHub Actions 才會自動部署）。

用法：
  python setup_automation.py
  GITHUB_PAT=ghp_xxx python setup_automation.py     # 一併設定推送憑證
"""
import os
import sys
import json
import subprocess
import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
VENV_PY = r"C:\Users\acer\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
EXTRACT = os.path.join(BASE, "extract_day.py")
RUNNER = os.path.join(BASE, "runner.bat")

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


def log(m):
    print(m, flush=True)


def main():
    games_dir = os.path.join(BASE, "games")

    # 1) 取得 switchClock
    meta = None
    if os.path.isdir(games_dir):
        for gid in os.listdir(games_dir):
            mp = os.path.join(games_dir, gid, "meta.json")
            if os.path.exists(mp):
                meta = json.load(open(mp, encoding="utf-8"))
                break
    switch = meta.get("switchClock") if meta else None

    if not switch:
        log("[..] 嘗試即時擷取以取得切日鐘點…")
        try:
            r = subprocess.run([VENV_PY, EXTRACT, "--no-build"], cwd=BASE)
            if r.returncode == 0 and os.path.isdir(games_dir):
                for gid in os.listdir(games_dir):
                    mp = os.path.join(games_dir, gid, "meta.json")
                    if os.path.exists(mp):
                        meta = json.load(open(mp, encoding="utf-8"))
                        switch = meta.get("switchClock")
                        break
        except Exception as e:
            log(f"[WARN] 即時擷取失敗：{e}")
        if not switch:
            switch = "17:00"
            log(f"[WARN] 無法即時取得切日鐘點，使用預設 {switch}（遊戲開啟後重跑本腳本可自動校正）。")

    st = (datetime.datetime.strptime(switch, "%H:%M") + datetime.timedelta(minutes=5)).strftime("%H:%M")
    log(f"排程時間：每日 {st}（切日 {switch} + 5 分）")

    # 2) 註冊 Windows 工作排程器
    task = ["schtasks", "/Create", "/TN", "Supremacy1914Daily",
            "/TR", f'cmd /c "{RUNNER}"', "/SC", "DAILY", "/ST", st, "/F"]
    res = subprocess.run(task, capture_output=True, text=True)
    if res.returncode == 0:
        log(f"[OK] 已註冊工作排程 Supremacy1914Daily（每日 {st} 執行 runner.bat）。")
    else:
        log(f"[ERR] 註冊失敗：{res.stderr}\n可手動執行：{' '.join(task)}")

    # 3) 設定 git 推送憑證（若提供 PAT）
    pat = os.environ.get("GITHUB_PAT")
    if pat:
        cred = os.path.expanduser("~/.git-credentials")
        line = f"https://__token__:{pat}@github.com\n"
        existing = ""
        if os.path.exists(cred):
            existing = open(cred, encoding="utf-8").read()
        if line not in existing:
            with open(cred, "a", encoding="utf-8") as f:
                f.write(line)
        subprocess.run(["git", "config", "--global", "credential.helper", "store"], cwd=BASE)
        log("[OK] 已設定 GitHub 推送憑證（PAT 存入 ~/.git-credentials，每日推送免互動）。")
        log("     ⚠️ 建議確認自動化正常後到 GitHub 撤銷此 PAT（Settings → Developer settings → Tokens）。")
    else:
        log("[INFO] 未設定 GITHUB_PAT 環境變數；若 git push 需互動，請設定後重跑本腳本。")


if __name__ == "__main__":
    main()
