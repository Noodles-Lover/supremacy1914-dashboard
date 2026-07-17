# -*- coding: utf-8 -*-
"""
Supremacy 1914 — 一次性自動化設定（僅需執行一次）。

職責：
  1. 確保 games/{gameID}/meta.json 存在並含 switchClock（切日鐘點）。
     若遊戲分頁當下開著 → 即時擷取取得；否則用預設 17:00（遊戲開啟後重跑本腳本會自動校正）。
  2. 用 Windows 工作排程器（schtasks）註冊每日工作 Supremacy1914Daily，
     執行 runner.bat（→ run_daily.py）。排程時間取自 automation.json 的 scheduleTime（預設 17:05，可手動編輯）。
  3. 推送認證（本機 git push 用）：優先 SSH——remote 為 git@ / ssh:// 即視為已設定，
     無需任何 PAT；僅當 remote 仍是 HTTPS 且提供 GITHUB_PAT 時，才回退將 PAT 嵌入 remote URL。
     （部署本身由 GitHub Actions 用 GITHUB_TOKEN 完成，與本機推送認證方式無關。）

用法：
  python setup_automation.py
  GITHUB_PAT=ghp_xxx python setup_automation.py     # 僅 HTTPS 舊方案才需要，SSH 方案免設
"""
import os
import sys
import json
import subprocess
import datetime
import tempfile

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


def get_username():
    """取得目前登入使用者（DOMAIN\\user 或 user@domain），用於任務主體。"""
    try:
        out = subprocess.run(["whoami"], capture_output=True, text=True)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return os.environ.get("USERNAME", "SYSTEM")


def build_task_xml(schedule_time, runner_path, username):
    """產生一個健壯的 Windows 任務計劃器 XML 定義。

    關鍵設定（解決排程靜默失效）：
      - StartWhenAvailable=true      ：錯過排程（如筆電休眠喚醒）後盡快補跑
      - DisallowStartIfOnBatteries=false ：即便用電池也照常執行
      - StopIfGoingOnBatteries=false      ：切到電池不中途中止
      - RestartOnFailure（3 次/間隔 1 分）：啟動失敗自動重試
      - RunOnlyIfLoggedOn=true           ：使用者已登入即執行（免存密碼）
    """
    today = datetime.date.today().isoformat()
    start = f"{today}T{schedule_time}:00"
    xml = f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Date>{today}T00:00:00</Date>
    <Author>{username}</Author>
    <Description>Supremacy 1914 每日擷取與部署（由 runner.bat 執行）</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{start}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{username}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfLoggedOn>true</RunOnlyIfLoggedOn>
    <ExecutionTimeLimit>PT1H</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>cmd.exe</Command>
      <Arguments>/c "{runner_path}"</Arguments>
    </Exec>
  </Actions>
</Task>'''
    return xml


def register_task(schedule_time):
    """用 XML 定義註冊/覆寫 Supremacy1914Daily 任務；失敗則回退簡易 /Create。"""
    username = get_username()
    xml = build_task_xml(schedule_time, RUNNER, username)
    fd, tmp = tempfile.mkstemp(suffix=".xml", prefix="s1914_task_")
    os.close(fd)
    try:
        # schtasks /Create /XML 需要 UTF-16 LE（含 BOM）
        with open(tmp, "w", encoding="utf-16") as f:
            f.write(xml)
        res = subprocess.run(
            ["schtasks", "/Create", "/TN", "Supremacy1914Daily", "/XML", tmp, "/F"],
            capture_output=True, text=True)
        if res.returncode == 0:
            log(f"[OK] 已用健壯 XML 定義註冊工作排程 Supremacy1914Daily（每日 {schedule_time}）。")
            log("     關鍵設定：喚醒補跑 / 允許電池執行 / 啟動失敗自動重試 3 次。")
            return True
        log(f"[WARN] XML 註冊失敗：{res.stderr.strip() or res.stdout.strip()}；回退簡易註冊…")
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass
    # 回退：簡易註冊（仍可用，但無電池/補跑強化）
    res = subprocess.run(
        ["schtasks", "/Create", "/TN", "Supremacy1914Daily",
         "/TR", f'cmd /c "{RUNNER}"', "/SC", "DAILY", "/ST", schedule_time, "/F"],
        capture_output=True, text=True)
    if res.returncode == 0:
        log(f"[OK] 已註冊工作排程 Supremacy1914Daily（每日 {schedule_time}，簡易模式）。")
        return True
    log(f"[ERR] 註冊失敗：{res.stderr.strip()}\n可手動執行：schtasks /Create /TN Supremacy1914Daily /TR \"cmd /c {RUNNER}\" /SC DAILY /ST {schedule_time} /F")
    return False


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

    # 2) 註冊 Windows 工作排程器（用健壯 XML 定義，避免靜默失效）
    register_task(st)

    # 3) 推送認證：SSH 優先（推薦，無需 PAT）
    #    remote 已是 SSH（git@ / ssh://）即表示用 SSH key 部署，無需任何憑證設定。
    #    僅當 remote 仍是 HTTPS 且提供 GITHUB_PAT 時，才回退嵌入 PAT（舊方案）。
    try:
        cur = subprocess.run(["git", "remote", "get-url", "origin"], cwd=BASE,
                             capture_output=True, text=True).stdout.strip()
    except Exception:
        cur = ""
    if cur.startswith("git@") or cur.startswith("ssh://"):
        log(f"[OK] remote 為 SSH（{cur.split('@')[-1]}），已用 SSH key 部署，無需 PAT，每日推送免互動。")
    elif os.environ.get("GITHUB_PAT"):
        pat = os.environ["GITHUB_PAT"]
        try:
            url = f"https://__token__:{pat}@github.com/Noodles-Lover/supremacy1914-dashboard.git"
            subprocess.run(["git", "remote", "set-url", "origin", url], cwd=BASE, check=True, capture_output=True, text=True)
            log("[OK] 已將 PAT 嵌入 remote URL（HTTPS 回退方案）。建議改用 SSH 後到 GitHub 撤銷此 PAT。")
        except Exception as e:
            log(f"[WARN] 無法自動設定推送憑證：{e}；請確保 git push origin main 可成功。")
    else:
        log("[INFO] remote 非 SSH 且未設定 GITHUB_PAT；請確保 git push origin main 可成功（或改用 SSH 部署）。")


if __name__ == "__main__":
    main()
