"""Native GUI launcher and isolated service entrypoint; no external downloads at runtime."""

import argparse
import json
import os
import sys
import threading
import webbrowser
from pathlib import Path

from native_runtime import Runtime, install, read_state, service


def gui():
    import tkinter as tk
    from tkinter import messagebox, ttk

    root = tk.Tk()
    root.title("LeadHive — Docker不要版（試作）")
    root.geometry("630x650")
    frame = ttk.Frame(root, padding=20)
    frame.pack(fill="both", expand=True)
    path = Path(os.environ["LOCALAPPDATA"]) / "LeadHiveNative" / "instance-v1"
    runtime = Runtime(path)
    ttk.Label(
        frame, text="LeadHiveをこのPCで使う", font=("Yu Gothic UI", 16, "bold")
    ).pack(anchor="w")
    ttk.Label(
        frame,
        text="Docker・WSL・Python・Nodeの事前インストールは不要です。\n試作版は送信OFF固定です。既存Docker版のデータは変更しません。",
    ).pack(anchor="w", pady=10)
    ttk.Label(frame, text=f"データ保存先：{path}", wraplength=560).pack(anchor="w")
    inputs = []
    for label, secret in [
        ("初回管理者メールアドレス", False),
        ("パスワード（12文字以上）", True),
        ("パスワード再入力", True),
    ]:
        ttk.Label(frame, text=label).pack(anchor="w", pady=(10, 0))
        entry = ttk.Entry(frame, show="*" if secret else "", width=60)
        entry.pack(fill="x")
        inputs.append(entry)
    status = tk.StringVar(
        value="初回は管理者情報を入力し「セットアップ」を押してください。"
    )
    ttk.Label(frame, textvariable=status, wraplength=560).pack(anchor="w", pady=15)
    buttons = []

    def task(action):
        for button in buttons:
            button.configure(state="disabled")
        status.set("処理中です。数分かかる場合があります。")

        def run():
            try:
                action()
                root.after(
                    0, lambda: status.set("完了しました。画面を開いて利用できます。")
                )
            except Exception as error:  # noqa: BLE001 -- GUI boundary must redact exceptions.
                kind = type(error).__name__
                root.after(
                    0,
                    lambda: status.set(
                        f"処理を完了できませんでした（{kind}）。データを削除せず診断ログを確認してください。"
                    ),
                )
                root.after(
                    0,
                    lambda: messagebox.showerror(
                        "LeadHive",
                        "処理に失敗しました。\n保存フォルダのruntime.logを確認してください。\nデータを削除したり再セットアップしたりしないでください。",
                    ),
                )
            finally:
                root.after(
                    0, lambda: [button.configure(state="normal") for button in buttons]
                )

        threading.Thread(target=run, daemon=True).start()

    def setup():
        email, password, confirmation = [entry.get() for entry in inputs]
        if password != confirmation or len(password) < 12 or "@" not in email:
            messagebox.showerror(
                "入力確認",
                "メールアドレスと12文字以上の同じパスワードを入力してください。",
            )
            return
        task(lambda: install(path, email, password))

    for label, command in [
        ("初回セットアップ", setup),
        ("起動して画面を開く", lambda: task(lambda: webbrowser.open(runtime.start()))),
        ("停止", lambda: task(runtime.stop)),
        (
            "保存フォルダ・診断ログ",
            lambda: (
                os.startfile(path)
                if path.exists()
                else messagebox.showinfo("LeadHive", "まだセットアップしていません。")
            ),
        ),
    ]:
        button = ttk.Button(frame, text=label, command=command)
        button.pack(fill="x", pady=3)
        buttons.append(button)

    def close():
        if any(str(button.cget("state")) == "disabled" for button in buttons):
            messagebox.showinfo("LeadHive", "処理が完了してから閉じてください。")
            return
        try:
            if (path / "instance.json").exists():
                runtime.stop()
        except Exception:  # noqa: BLE001 -- preserve data when shutdown cannot be verified.
            messagebox.showerror(
                "LeadHive", "停止を確認できません。診断ログを確認してください。"
            )
            return
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)
    root.mainloop()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", choices=["migrate", "admin", "api", "worker"])
    parser.add_argument("--data")
    parser.add_argument("--smoke-report")
    args = parser.parse_args()
    if args.service:
        service(args.service, Path(args.data))
    elif args.smoke_report:
        smoke(Path(args.data), Path(args.smoke_report))
    else:
        gui()


def smoke(data, output):
    """Explicit disposable native acceptance. Never use operational/Docker instance paths."""
    import secrets
    import urllib.request

    if "native-acceptance-" not in data.name or data.exists():
        raise ValueError("Smoke requires a new dedicated native acceptance folder")
    runtime = Runtime(data)
    from urllib.error import HTTPError

    from native_runtime import db_connection, environment

    result = {
        "worker_started": False,
        "external_service_calls": "not invoked by this test",
    }
    password = secrets.token_hex(20)
    try:
        install(data, "native-acceptance@example.com", password)
        url = runtime.start()
        import http.cookiejar

        browser = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        login = urllib.request.Request(
            url + "api/auth/login",
            data=json.dumps(
                {"email": "native-acceptance@example.com", "password": password}
            ).encode(),
            headers={"Content-Type": "application/json", "Origin": url.rstrip("/")},
        )
        with browser.open(login, timeout=10) as r:
            result["admin_login"] = r.status == 200
        with browser.open(url + "api/auth/me", timeout=5) as r:
            result["session"] = r.status == 200
        with urllib.request.urlopen(url + "api/health", timeout=5) as r:
            result["health"] = json.load(r)
        with urllib.request.urlopen(url, timeout=5) as r:
            result["frontend"] = r.status
        with urllib.request.urlopen(url + "openapi.json", timeout=5) as r:
            result["approval_api"] = (
                "/api/approval-requests/{request_id}/approve" in json.load(r)["paths"]
            )
        result["outbound"] = environment(data)["OUTBOUND_ENABLED"]
        with db_connection(data, "leadhive_native") as db:
            result["records"] = {
                table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in (
                    "email_deliveries",
                    "form_deliveries",
                    "approval_requests",
                    "users",
                )
            }
        try:
            urllib.request.urlopen(url + "api/not-a-real-endpoint", timeout=5)
        except HTTPError as error:
            result["unknown_api_status"] = error.code
        before = read_state(data)
        runtime.stop()
        runtime.start()
        result["restart_same_instance"] = read_state(data)["id"] == before["id"]
        result["success"] = (
            result["approval_api"]
            and result["frontend"] == 200
            and result["restart_same_instance"]
            and result["unknown_api_status"] == 404
            and result["records"]
            == {
                "email_deliveries": 0,
                "form_deliveries": 0,
                "approval_requests": 0,
                "users": 1,
            }
        )
    except Exception as error:
        result["success"] = False
        result["error_type"] = type(error).__name__
        raise
    finally:
        try:
            if (data / "instance.json").exists():
                runtime.stop()
        except Exception as error:  # noqa: BLE001 -- always save a redacted test result.
            result["stop_error_type"] = type(error).__name__
            result["success"] = False
        output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    if not result["success"]:
        raise RuntimeError("Native acceptance failed")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 -- never expose credentials through tracebacks.
        import traceback

        # Log exception type and frame locations, never exception values or source lines.
        diagnostic = {
            "error_type": type(error).__name__,
            "frames": [
                {
                    "file": Path(frame.filename).name,
                    "line": frame.lineno,
                    "function": frame.name,
                }
                for frame in traceback.extract_tb(error.__traceback__)[-5:]
            ],
        }
        if isinstance(error, ModuleNotFoundError):
            diagnostic["missing_module"] = error.name
        if sys.stderr is not None:
            sys.stderr.write(json.dumps(diagnostic) + "\n")
        sys.exit(1)
