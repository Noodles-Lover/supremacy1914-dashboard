# -*- coding: utf-8 -*-
"""
Supremacy 1914 — 直接部署到 gh-pages（不經 GitHub Actions）。

做法：用 git worktree 在系統暫存區簽出 gh-pages，複製生成的
index.html（來自 supremacy1914_dashboard.html）與 games/ 數據備份，
提交後推送 gh-pages。主分支 main 完全不動，因此 main 只會在改代碼時才 commit。

用法：
  python deploy_ghpages.py            # 部署（需能 push 到 origin/gh-pages，依賴 Git Credential Manager）
  python deploy_ghpages.py --no-push  # 只在本機 worktree 建好並提交，不推送（測試用）
  python deploy_ghpages.py --force    # 即使無變更也重新部署（手動重部署）
"""
import os
import sys
import shutil
import tempfile
import subprocess
import argparse
import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
HTML = os.path.join(BASE, "supremacy1914_dashboard.html")
GAMES = os.path.join(BASE, "games")

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


def run_git(*args, check=True, cwd=BASE):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失敗：{r.stderr.strip()}")
    return r


def deploy(no_push=False, force=False):
    if not os.path.exists(HTML):
        raise RuntimeError("找不到 supremacy1914_dashboard.html，請先重建儀表盤。")

    # 清理上一次可能殘留的 worktree 記錄
    run_git("worktree", "prune", check=False)

    wt = tempfile.mkdtemp(prefix="sup_deploy_")
    os.rmdir(wt)  # git worktree add 需要路徑「不存在」
    try:
        # 確保能拿到最新的 gh-pages（公開倉庫無憑證也可 fetch）
        run_git("fetch", "origin", "gh-pages", check=False)
        # 若本地已有 gh-pages 分支（上次 remove 未清乾淨），先刪除避免衝突
        run_git("branch", "-D", "gh-pages", check=False)
        run_git("worktree", "add", wt, "origin/gh-pages")

        # 複製生成物：index.html（站點入口）
        shutil.copyfile(HTML, os.path.join(wt, "index.html"))
        # 數據備份：整個 games/ 複製過去（含 day_*.json，作為離機備份）
        dst_games = os.path.join(wt, "games")
        if os.path.isdir(GAMES):
            if os.path.isdir(dst_games):
                shutil.rmtree(dst_games)
            shutil.copytree(GAMES, dst_games)

        run_git("add", "-A", cwd=wt)
        diff = run_git("diff", "--cached", "--quiet", cwd=wt, check=False)
        if diff.returncode == 0 and not force:
            print("[INFO] gh-pages 內容無變更，跳過推送。")
            return
        msg = f"deploy: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"
        run_git("commit", "-m", msg, cwd=wt)
        if no_push:
            print(f"[DRY] 已在本機 worktree 提交（{wt}），跳過推送。")
            return
        run_git("push", "origin", "gh-pages", cwd=wt)
        print(f"[OK] 已推送 gh-pages（{msg}）。")
    finally:
        # 清理 worktree（會一併移除本地 gh-pages 分支，下次從 origin 重新簽出）
        run_git("worktree", "remove", "--force", wt, check=False)
        run_git("worktree", "prune", check=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-push", action="store_true", help="本機建好 worktree 並提交但不推送（測試用）")
    ap.add_argument("--force", action="store_true", help="即使無變更也重新部署")
    args = ap.parse_args()
    deploy(no_push=args.no_push, force=args.force)


if __name__ == "__main__":
    main()
