# -*- coding: utf-8 -*-
"""
Supremacy 1914 — 一次性自動化設定（僅需執行一次）。

職責：
  1. 確保 games/{gameID}/meta.json 存在並含 switchClock（切日鐘點）。
     若遊戲分頁當下開著 → 即時擷取取得；否則用預設 17:00（遊戲開啟後重跑本腳本會自動校正）。
  2. 用 Windows 工作排程器（schtasks）註冊每日工作 Supremacy1914Daily，
     執行 runner.bat（→ run_daily.py）。排程時間取自 automation.json 的 scheduleTime（預設 17:05，可手動編輯）。
  3. 若環境變數 GITHUB_PAT 已設定，將其寫入本倉庫 .git/config 的 remote URL，
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

    # 0) 讀取自動化設定（使用者可手動編輯 automation.json 調整排程時間 / 重試參數）
    cfg_path = os.path.join(BASE, "automation.json")
    cfg = {"scheduleTime": "17:05", "retryMinutes": 10, "retryWindowHours": 4}
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception:
            pass
    else:
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        log(f"[OK] 已建立 automation.json（預設排程 {cfg['scheduleTime']}，可手動編輯後重跑本腳本生效）。")

    # 1) 確保 meta.json 存在（遊戲開著則即時擷取；否則用預設，日後重跑自動校正）
    meta = None
    if os.path.isdir(games_dir):
        for gid in os.listdir(games_dir):
            mp = os.path.join(games_dir, gid, "meta.json")
            if os.path.exists(mp):
                meta = json.load(open(mp, encoding="utf-8"))
                break
    if not meta:
        log("[..] 嘗試即時擷取以建立 meta.json（含 switchClock / 我的 ID）…")
        try:
            subprocess.run([VENV_PY, EXTRACT, "--no-build"], cwd=BASE)
            if os.path.isdir(games_dir):
                for gid in os.listdir(games_dir):
                    mp = os.path.join(games_dir, gid, "meta.json")
                    if os.path.exists(mp):
                        meta = json.load(open(mp, encoding="utf-8"))
                        break
        except Exception as e:
            log(f"[WARN] 即時擷取失敗：{e}")
        if not meta:
            log("[WARN] 無法建立 meta.json（遊戲未開）。排程仍會註冊；開遊戲後重跑本腳本可補建。")

    st = cfg.get("scheduleTime", "17:05")
    log(f"排程時間：每日 {st}（來源：automation.json 手動設定）")

    # 2) 註冊 Windows 工作排程器
    task = ["schtasks", "/Create", "/TN", "Supremacy1914Daily",
            "/TR", f'cmd /c "{RUNNER}"', "/SC", "DAILY", "/ST", st, "/F"]
    res = subprocess.run(task, capture_output=True, text=True)
    if res.returncode == 0:
        log(f"[OK] 已註冊工作排程 Supremacy1914Daily（每日 {st} 執行 runner.bat）。")
    else:
        log(f"[ERR] 註冊失敗：{res.stderr}\n可手動執行：{' '.join(task)}")

    # 3) 設定 git 推送憑證（若提供 PAT）。寫入本倉庫 .git/config 的 remote URL（僅本機，非使用者主目錄）。
    pat = os.environ.get("GITHUB_PAT")
    if pat:
        try:
            url = f"https://__token__:{pat}@github.com/Noodles-Lover/supremacy1914-dashboard.git"
            subprocess.run(["git", "remote", "set-url", "origin", url], cwd=BASE, check=True, capture_output=True, text=True)
            log("[OK] 已將推送憑證嵌入本倉庫 remote URL（.git/config，每日推送免互動）。")
            log("     ⚠️ 建議確認自動化正常後到 GitHub 撤銷此 PAT（Settings → Developer settings → Tokens）。")
        except Exception as e:
            log(f"[WARN] 無法自動設定推送憑證：{e}")
            log("       請確保 git push origin main 可成功（手動推送一次或另行設定憑證），每日自動化才能推送。")
    else:
        log("[INFO] 未設定 GITHUB_PAT；請確保 git push origin main 可成功，每日自動化才能推送並觸發部署。")


if __name__ == "__main__":
    main()
