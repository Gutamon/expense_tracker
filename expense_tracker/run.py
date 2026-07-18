import os
import subprocess

from app.views import create_app, start_rate_scheduler

app = create_app()


def _kill_stale_port(port: int) -> None:
    """Windows 專用：啟動前清掉卡在該 port 的殘留進程（例如上次 debug reloader 沒正常關閉）。"""
    if os.name != "nt":
        return
    try:
        result = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, check=True
        )
    except Exception:
        return
    pids = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0] == "TCP" and f":{port}" in parts[1] and parts[3] == "LISTENING":
            pids.add(parts[4])
    for pid in pids:
        subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)


if __name__ == "__main__":
    _kill_stale_port(5000)
    # debug=True 的 reloader 會先在監控進程執行這整個 __main__ 區塊一次（此時
    # WERKZEUG_RUN_MAIN 尚未設定，該進程只負責 spawn 子進程後結束），子進程重新
    # import 整個模組時才會帶著 WERKZEUG_RUN_MAIN=true 真正呼叫 app.run() 處理請求。
    # 排程器只能在真正服務請求的那個進程啟動一次，否則兩個進程各跑一份、匯率每天
    # 會被更新兩次。
    if os.environ.get("WERKZEUG_RUN_MAIN") is not None:
        start_rate_scheduler(app)
    # debug=True 會在程式碼修改時自動重新載入，適合開發時使用
    app.run(host="0.0.0.0", port=5000, debug=True)