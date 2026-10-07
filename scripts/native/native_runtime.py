"""Windows native prototype: dedicated PostgreSQL, DPAPI secrets, outbound OFF."""

import ctypes
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

HIDDEN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
OFF_FLAGS = (
    "OUTBOUND_ENABLED",
    "HUMAN_APPROVED_EMAIL_ENABLED",
    "HUMAN_APPROVED_FORM_ENABLED",
    "LEGACY_FORM_DELIVERY_ENABLED",
    "AGENT_FEATURES_ENABLED",
    "EMAIL_FEEDBACK_WEBHOOK_ENABLED",
)


def bundle():
    return (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parents[2] / "dist/native-dev"
    )


def checked_root(path):
    original = Path(path).absolute()
    for part in (original, *original.parents):
        if part.exists() and (
            part.is_symlink() or getattr(part, "is_junction", lambda: False)()
        ):
            raise ValueError("Reparse directories are not supported")
    root = original.resolve()
    if root == Path(root.anchor) or root.anchor.startswith("\\\\"):
        raise ValueError("Invalid instance directory")
    return root


def protect(data, decrypt=False):
    """Secrets can only be decrypted by this Windows user on this PC."""
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    function = (
        ctypes.windll.crypt32.CryptUnprotectData
        if decrypt
        else ctypes.windll.crypt32.CryptProtectData
    )
    if not function(
        ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)
    ):
        raise OSError("Windows secret protection failed")
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        free = ctypes.windll.kernel32.LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        free(output.data)


def free_port(start):
    for port in range(start, start + 50):
        try:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    raise RuntimeError("No available loopback port")


def read_state(root, ready=True):
    root = checked_root(root)
    state = json.loads((root / "instance.json").read_text(encoding="utf-8"))
    if state.get("format") != "leadhive-native-v1" or str(root) != state.get("root"):
        raise ValueError("Instance identity or directory mismatch")
    uuid.UUID(state["id"])
    if ready and state.get("phase") != "READY":
        raise RuntimeError(
            "Incomplete installation. Preserve this folder and use diagnostics."
        )
    for name in ("db_port", "web_port"):
        if type(state.get(name)) is not int or not 1024 <= state[name] <= 65535:
            raise ValueError("Invalid local port")
    return state


def save_state(root, state):
    target = root / "instance.json"
    temp = root / "instance.json.new"
    temp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    temp.replace(target)


def secret_values(root):
    return json.loads(protect((root / "secrets.bin").read_bytes(), decrypt=True))


def environment(root):
    state = read_state(root, ready=False)
    value = secret_values(root)
    # No inherited provider/SMTP credentials or Python path from the host PC.
    env = {
        k: v
        for k, v in os.environ.items()
        if k.upper()
        in {
            "SYSTEMROOT",
            "WINDIR",
            "TEMP",
            "TMP",
            "LOCALAPPDATA",
            "USERPROFILE",
            "APPDATA",
            "COMSPEC",
        }
    }
    env.update(
        DATABASE_URL=f"postgresql+psycopg://postgres:{value['database_password']}@127.0.0.1:{state['db_port']}/leadhive_native",
        SETTINGS_ENCRYPTION_KEY=value["encryption_key"],
        PUBLIC_APP_URL=f"http://127.0.0.1:{state['web_port']}",
        CORS_ORIGINS=f"http://127.0.0.1:{state['web_port']}",
        COOKIE_SECURE="false",
        WORKER_PAUSED="false",
        PYTHONNOUSERSITE="1",
    )
    env.update({key: "false" for key in OFF_FLAGS})
    return env


def command(root, executable, *args):
    exe = bundle() / "postgresql/bin" / executable
    if not exe.is_file():
        raise RuntimeError("Bundled PostgreSQL is missing")
    # Frozen Python's DLL search directory must not contaminate PostgreSQL's DLL loading.
    if getattr(sys, "frozen", False):
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    try:
        # pg_ctl's server child may inherit stdout. A PIPE would wait for daemon EOF.
        with (root / "postgres-setup.log").open("ab") as log:
            result = subprocess.run(
                [str(exe), *map(str, args)],
                cwd=root,
                creationflags=HIDDEN,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=120,
                check=False,
            )
    finally:
        if getattr(sys, "frozen", False):
            ctypes.windll.kernel32.SetDllDirectoryW(str(sys._MEIPASS))
    if result.returncode:
        # Do not show commands, passwords, connection URLs or raw exceptions.
        raise RuntimeError(f"PostgreSQL command failed: {executable}")


def db_connection(root, database="postgres"):
    import psycopg

    state = read_state(root, ready=False)
    value = secret_values(root)
    return psycopg.connect(
        host="127.0.0.1",
        port=state["db_port"],
        user="postgres",
        password=value["database_password"],
        dbname=database,
        connect_timeout=5,
        autocommit=True,
    )


def assert_cluster(root):
    state = read_state(root, ready=False)
    with db_connection(root) as db:
        identity = str(
            db.execute("SELECT system_identifier FROM pg_control_system()").fetchone()[
                0
            ]
        )
        data = cluster_directory(db)
    if (
        identity != state.get("cluster_id")
        or data != (root / "postgres-data").resolve()
    ):
        raise RuntimeError("Database instance mismatch")


def cluster_directory(db):
    # PostgreSQL on Windows may expose its filesystem path in the system ANSI codepage,
    # even when the database is UTF-8. Fetch bytes before psycopg's text decoder runs.
    from psycopg.adapt import Loader

    class PathBytesLoader(Loader):
        def load(self, data):
            return bytes(data)

    with db.cursor() as cursor:
        cursor.adapters.register_loader("text", PathBytesLoader)
        raw = cursor.execute("SHOW data_directory").fetchone()[0]
    try:
        value = raw.decode("utf-8")
    except UnicodeDecodeError:
        value = raw.decode(f"cp{ctypes.windll.kernel32.GetACP()}")
    return Path(value).resolve()


def start_db(root):
    root = checked_root(root)
    state = read_state(root, ready=False)
    if (root / "postgres-data/postmaster.pid").exists():
        assert_cluster(root)
        return
    command(
        root,
        "pg_ctl.exe",
        "-D",
        root / "postgres-data",
        "-l",
        root / "postgres.log",
        "-w",
        "start",
    )
    if state.get("cluster_id"):
        assert_cluster(root)


def stop_db(root):
    root = checked_root(root)
    read_state(root, ready=False)
    if (root / "postgres-data/postmaster.pid").exists():
        assert_cluster(root)
        command(
            root, "pg_ctl.exe", "-D", root / "postgres-data", "-m", "fast", "-w", "stop"
        )


def child(root, mode, input_data=None, wait=False):
    executable = (
        str(bundle() / "LeadHiveEngine.exe")
        if getattr(sys, "frozen", False)
        else sys.executable
    )
    args = [executable, "--service", mode, "--data", str(root)]
    if not getattr(sys, "frozen", False):
        args.insert(1, str(Path(__file__).with_name("entry.py")))
    log = (root / "runtime.log").open("ab")
    process = subprocess.Popen(
        args,
        cwd=root,
        env=environment(root),
        creationflags=HIDDEN,
        stdin=subprocess.PIPE if input_data else subprocess.DEVNULL,
        stdout=log,
        stderr=log,
    )
    log.close()
    if wait:
        try:
            process.communicate(
                json.dumps(input_data).encode() if input_data else None, timeout=180
            )
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise RuntimeError("Local installation step timed out") from None
        if process.returncode:
            raise RuntimeError(f"Local step failed: {mode}. See diagnostics.")
    return process


def install(root, email, password):
    from cryptography.fernet import Fernet
    from pydantic import EmailStr, TypeAdapter

    email = str(TypeAdapter(EmailStr).validate_python(email)).lower()
    if not 12 <= len(password) <= 1024:
        raise ValueError("Password length invalid")

    root = checked_root(root)
    root.mkdir(parents=True, exist_ok=True)
    # Directory adoption, partial reinstall and overwrite are deliberately prohibited.
    if any(root.iterdir()):
        raise RuntimeError(
            "Installation folder is not empty. Existing data is never overwritten."
        )
    sid = (
        subprocess.check_output(
            ["whoami", "/user", "/fo", "csv", "/nh"], creationflags=HIDDEN, text=True
        )
        .strip()
        .split(",")[-1]
        .strip('"')
    )
    subprocess.run(
        ["icacls", str(root), "/inheritance:r", "/grant:r", f"*{sid}:(OI)(CI)F"],
        check=True,
        creationflags=HIDDEN,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    state = {
        "format": "leadhive-native-v1",
        "id": str(uuid.uuid4()),
        "root": str(root),
        "phase": "INSTALLING",
        "db_port": free_port(25432),
        "web_port": free_port(18990),
    }
    save_state(root, state)
    (root / "runtime.log").write_text(
        "Native installation started; external sending disabled.\n", encoding="utf-8"
    )
    values = {
        "database_password": secrets.token_hex(32),
        "encryption_key": Fernet.generate_key().decode(),
    }
    (root / "secrets.bin").write_bytes(protect(json.dumps(values).encode()))
    pwfile = root / "init-password.tmp"
    try:
        pwfile.write_text(values["database_password"], encoding="utf-8")
        command(
            root,
            "initdb.exe",
            "-D",
            root / "postgres-data",
            "-U",
            "postgres",
            "--pwfile",
            pwfile,
            "--auth-host=scram-sha-256",
            "--auth-local=scram-sha-256",
            "--encoding=UTF8",
            "--locale=C",
        )
    finally:
        pwfile.unlink(missing_ok=True)
    with (root / "postgres-data/postgresql.conf").open("a", encoding="utf-8") as f:
        f.write(
            f"\nlisten_addresses='127.0.0.1'\nport={state['db_port']}\nmax_connections=50\n"
        )
    start_db(root)
    with db_connection(root) as db:
        if cluster_directory(db) != (root / "postgres-data").resolve():
            raise RuntimeError("Database instance mismatch")
        state["cluster_id"] = str(
            db.execute("SELECT system_identifier FROM pg_control_system()").fetchone()[
                0
            ]
        )
        db.execute("CREATE DATABASE leadhive_native")
    save_state(root, state)
    try:
        child(root, "migrate", wait=True)
        child(root, "admin", {"email": email, "password": password}, wait=True)
    except Exception:
        stop_db(root)
        raise
    state["phase"] = "READY"
    save_state(root, state)
    stop_db(root)


class Runtime:
    def __init__(self, root):
        self.root = checked_root(root)
        self.processes = []
        self.lock = None
        self.db_owned = False

    def start(self, worker=False):

        state = read_state(self.root)
        if self.processes:
            raise RuntimeError("This launcher already owns a running instance")
        # Hold an OS file lock throughout this launcher's ownership. It is released on crash.
        import msvcrt

        self.lock = (self.root / "runtime.lock").open("a+b")
        self.lock.seek(0)
        self.lock.write(b"1")
        self.lock.flush()
        self.lock.seek(0)
        try:
            msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.lock.close()
            self.lock = None
            raise RuntimeError("Another launcher owns this instance") from None
        try:
            return self._start_locked(state, worker)
        except Exception:
            self.stop()
            raise

    def _start_locked(self, state, worker):
        import urllib.request

        # Fail closed before taking database ownership when this web port is occupied.
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", state["web_port"]))
        start_db(self.root)
        self.db_owned = True
        # A copied/newer executable may not silently serve an older database schema.
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        config = Config()
        migration_path = (
            Path(sys._MEIPASS) / "migrations"
            if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parents[2] / "backend/migrations"
        )
        config.set_main_option("script_location", str(migration_path))
        expected = set(ScriptDirectory.from_config(config).get_heads())
        with db_connection(self.root, "leadhive_native") as db:
            actual = {
                r[0]
                for r in db.execute(
                    "SELECT version_num FROM alembic_version"
                ).fetchall()
            }
        if expected != actual:
            stop_db(self.root)
            raise RuntimeError(
                "Database schema mismatch. Automatic updates are not supported."
            )
        self.processes.append(child(self.root, "api"))
        for _ in range(60):
            if self.processes[0].poll() is not None:
                raise RuntimeError("API stopped during startup. See diagnostics.")
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{state['web_port']}/api/health", timeout=2
                ) as r:
                    if r.status == 200:
                        if worker:
                            self.processes.append(child(self.root, "worker"))
                        return f"http://127.0.0.1:{state['web_port']}/"
            except OSError:
                pass
            time.sleep(0.5)
        raise RuntimeError("API startup timed out. See diagnostics.")

    def stop(self):
        if self.lock is None:
            return
        for process in reversed(self.processes):
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=15)
        self.processes.clear()
        if self.db_owned:
            stop_db(self.root)
            self.db_owned = False
        self.lock.close()
        self.lock = None


def service(mode, root):
    root = checked_root(root)
    assert_cluster(root)
    env = environment(root)
    os.environ.clear()
    os.environ.update(env)
    if mode == "migrate":
        from alembic import command as alembic_command
        from alembic.config import Config

        config = Config()
        config.set_main_option(
            "script_location", str(Path(sys._MEIPASS) / "migrations")
        )
        alembic_command.upgrade(config, "head")
    elif mode == "admin":
        from app.database import SessionLocal
        from app.models import User
        from app.security import password_hasher
        from pydantic import EmailStr, TypeAdapter
        from sqlalchemy import select

        data = json.loads(sys.stdin.buffer.read())
        email = str(TypeAdapter(EmailStr).validate_python(data["email"])).lower()
        if not 12 <= len(data["password"]) <= 1024:
            raise ValueError("Password length invalid")
        with SessionLocal() as db:
            if db.scalar(select(User.id).limit(1)):
                raise RuntimeError("Administrator already exists")
            db.add(
                User(
                    email=email,
                    password_hash=password_hasher.hash(data["password"]),
                    is_admin=True,
                )
            )
            db.commit()
    elif mode == "worker":
        from app.worker import main

        sys.argv = [sys.argv[0]]
        main()
    elif mode == "api":
        import uvicorn
        from app.main import app
        from fastapi.responses import FileResponse, JSONResponse
        from fastapi.staticfiles import StaticFiles

        web = Path(sys._MEIPASS) / "web"
        app.mount(
            "/assets", StaticFiles(directory=web / "assets"), name="native-assets"
        )

        @app.get("/{path:path}", include_in_schema=False)
        def frontend(path: str):
            if path == "api" or path.startswith("api/"):
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            return FileResponse(web / "index.html")

        uvicorn.run(
            app, host="127.0.0.1", port=read_state(root)["web_port"], access_log=False
        )
    else:
        raise ValueError("Unknown service")
