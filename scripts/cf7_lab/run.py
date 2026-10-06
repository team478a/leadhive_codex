"""Opt-in isolated real WordPress/CF7 lab. Never imports LeadHive app/DB settings."""

import hashlib
import io
import json
import os
import secrets
import subprocess
import time
import urllib.request
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from cases import verify
from gateway import gateway

ROOT = Path(__file__).resolve().parents[2]
ASSETS = Path(__file__).resolve().parent
CF7_COMMIT = "165278e868387ec393569ecd2dbfda37e8b5b950"
SOURCE_SHA = "7cfdd76cfa25ffd7a2f3c1cb245dd5be1ede8989a5347ade2fa8a839d943b5f1"
IMAGES = {"wp": "wordpress:6.8.3-php8.3-apache", "db": "mariadb:11.4"}
SECRET_VALUES = []


def command(*args, env=None, timeout=120):
    result = subprocess.run(
        list(args),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=timeout,
        check=False,
    )
    if result.returncode:
        # Do not echo arguments, Docker environment, installation passwords or full logs.
        diagnostic = result.stderr[:2000]
        for secret in SECRET_VALUES:
            diagnostic = diagnostic.replace(secret, "[redacted]")
        raise RuntimeError(
            f"{args[0]} operation failed ({result.returncode}): {diagnostic}"
        )
    return result.stdout.strip()


def docker(*args, **kwargs):
    return command("docker", *args, **kwargs)


def source():
    cache = ROOT / "dist" / "cf7-source-165278e"
    archive = cache / "source.zip"
    cache.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        request = urllib.request.Request(
            f"https://codeload.github.com/rocklobster-in/contact-form-7/zip/{CF7_COMMIT}"
        )
        with urllib.request.urlopen(request, timeout=45) as response:
            data = response.read(20_000_001)
        if len(data) > 20_000_000:
            raise RuntimeError("Source archive oversized")
        archive.write_bytes(data)
    data = archive.read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA:
        raise RuntimeError("Pinned source archive checksum mismatch")
    destination = cache / ("verified-source-" + uuid.uuid4().hex)
    destination.mkdir(exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as package:
        for item in package.infolist():
            parts = Path(item.filename).parts
            if not parts or parts[0] != "contact-form-7-" + CF7_COMMIT:
                raise RuntimeError("Unexpected archive root")
            target = (destination / Path(*parts[1:])).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise RuntimeError("Unsafe archive path")
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(package.read(item))
    return destination


def run():
    if os.environ.get("CF7_PROTOCOL_LAB") != "1":
        raise RuntimeError("Set CF7_PROTOCOL_LAB=1 explicitly")
    plugin = source()  # Acquisition before starting isolated runtime.
    image_records = {}
    for key, tag in IMAGES.items():
        inspected = json.loads(docker("image", "inspect", tag))[0]
        if not inspected["RepoDigests"]:
            raise RuntimeError(
                "Image digest unavailable; acquire official images first"
            )
        image_records[key] = {
            "tag": tag,
            "digest": inspected["RepoDigests"][0],
            "id": inspected["Id"],
        }
    prefix = "leadhive-cf7-lab-" + uuid.uuid4().hex[:12]
    output = ROOT / "dist" / prefix
    output.mkdir(parents=True, exist_ok=False)
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "cf7_commit": CF7_COMMIT,
        "source_sha256": SOURCE_SHA,
        "images": image_records,
        "checks": [],
        "live_changes": False,
        "real_companies_accessed": False,
        "lead_hive_dispatch_connected": False,
    }
    resources = []
    local_gateway = None
    env = os.environ.copy()
    env.update(
        {
            "MARIADB_ROOT_PASSWORD": secrets.token_urlsafe(32),
            "MARIADB_DATABASE": "cf7_lab",
            "MARIADB_USER": "cf7_lab",
            "MARIADB_PASSWORD": secrets.token_urlsafe(32),
            "WORDPRESS_DB_NAME": "cf7_lab",
            "WORDPRESS_DB_USER": "cf7_lab",
            "LEADHIVE_CF7_LAB": "1",
        }
    )
    env["WORDPRESS_DB_PASSWORD"] = env["MARIADB_PASSWORD"]
    SECRET_VALUES.extend([env["MARIADB_ROOT_PASSWORD"], env["MARIADB_PASSWORD"]])
    env["WORDPRESS_DB_HOST"] = prefix + "-db:3306"
    env["WORDPRESS_CONFIG_EXTRA"] = (
        "define('DISABLE_WP_CRON', true); define('WP_HTTP_BLOCK_EXTERNAL', true); "
        "define('AUTOMATIC_UPDATER_DISABLED', true); define('DISALLOW_FILE_MODS', true);"
    )
    network, db, wp = prefix + "-net", prefix + "-db", prefix + "-wp"
    volumes = [prefix + "-db-data", prefix + "-wp-data"]

    def check(name, condition, detail=None):
        report["checks"].append(
            {"name": name, "passed": bool(condition), "detail": detail}
        )
        if not condition:
            raise RuntimeError("Lab check failed: " + name)
        print("PASS: " + name, flush=True)

    def fixture(action, *args):
        return docker(
            "exec",
            "--user",
            "www-data",
            wp,
            "php",
            "/opt/cf7-lab/fixture.php",
            action,
            *args,
        )

    def evidence():
        return json.loads(fixture("evidence"))

    try:
        docker(
            "network",
            "create",
            "--internal",
            "--label",
            "leadhive.cf7.lab=" + prefix,
            network,
        )
        resources.append(("network", network))
        for volume in volumes:
            docker("volume", "create", "--label", "leadhive.cf7.lab=" + prefix, volume)
            resources.append(("volume", volume))
        db_args = [
            "run",
            "-d",
            "--name",
            db,
            "--label",
            "leadhive.cf7.lab=" + prefix,
            "--network",
            network,
            "--memory",
            "512m",
            "--cpus",
            "1",
            "-v",
            volumes[0] + ":/var/lib/mysql",
        ]
        for name in (
            "MARIADB_ROOT_PASSWORD",
            "MARIADB_DATABASE",
            "MARIADB_USER",
            "MARIADB_PASSWORD",
        ):
            db_args += ["--env", name]
        docker(*db_args, image_records["db"]["digest"], env=env)
        resources.append(("container", db))
        for attempt in range(90):
            try:
                docker(
                    "exec",
                    db,
                    "sh",
                    "-c",
                    'mariadb-admin ping -uroot -p"$MARIADB_ROOT_PASSWORD" --silent',
                )
                break
            except RuntimeError:
                time.sleep(1)
        else:
            raise RuntimeError("Lab DB startup timed out")
        wp_args = [
            "run",
            "-d",
            "--name",
            wp,
            "--label",
            "leadhive.cf7.lab=" + prefix,
            "--network",
            network,
            "--memory",
            "512m",
            "--cpus",
            "1",
            "-v",
            volumes[1] + ":/var/www/html",
            "--mount",
            f"type=bind,source={ASSETS},target=/opt/cf7-lab,readonly",
        ]
        for name in (
            "WORDPRESS_DB_HOST",
            "WORDPRESS_DB_NAME",
            "WORDPRESS_DB_USER",
            "WORDPRESS_DB_PASSWORD",
            "WORDPRESS_CONFIG_EXTRA",
            "LEADHIVE_CF7_LAB",
        ):
            wp_args += ["--env", name]
        docker(*wp_args, image_records["wp"]["digest"], env=env)
        resources.append(("container", wp))
        bindings = json.loads(
            docker("inspect", "--format", "{{json .NetworkSettings.Ports}}", wp)
        )
        bound = bindings.get("80/tcp")
        check(
            "container publishes no ports",
            not bound,
            bound,
        )
        requested = json.loads(
            docker("inspect", "--format", "{{json .HostConfig.PortBindings}}", wp)
        )
        check("no requested port publication", not requested)
        local_gateway = gateway(wp)
        origin = local_gateway.__enter__()
        report["origin"] = origin
        for attempt in range(60):
            try:
                docker("exec", wp, "test", "-f", "/var/www/html/wp-config.php")
                break
            except RuntimeError:
                pass
            time.sleep(1)
        else:
            raise RuntimeError("Lab WordPress startup timed out")
        docker("exec", wp, "mkdir", "-p", "/var/www/html/wp-content/mu-plugins")
        docker(
            "cp",
            str(ASSETS / "safeguard.php"),
            wp + ":/var/www/html/wp-content/mu-plugins/",
        )
        docker(
            "cp", str(plugin), wp + ":/var/www/html/wp-content/plugins/contact-form-7"
        )
        docker(
            "exec",
            "--env",
            "LAB_ORIGIN=" + origin,
            "--user",
            "www-data",
            wp,
            "php",
            "/opt/cf7-lab/fixture.php",
            "install",
        )
        report["versions"] = json.loads(fixture("create"))
        inspected_network = json.loads(docker("network", "inspect", network))[0]
        check("internal runtime network", inspected_network["Internal"] is True)
        for name in (wp, db):
            connected = json.loads(
                docker(
                    "inspect", "--format", "{{json .NetworkSettings.Networks}}", name
                )
            )
            check(
                name.rsplit("-", 1)[1] + " isolated network only",
                set(connected) == {network},
            )
        isolated = json.loads(fixture("isolation"))
        check(
            "WP HTTP and numeric external sockets blocked",
            isolated["wp_http_blocked"] and all(isolated["external_socket_blocked"]),
            isolated,
        )
        # Test capture before the first CF7 POST. This never invokes PHPMailer.
        initial_mail_calls = len(evidence()["mail_calls"])
        docker(
            "exec",
            "--user",
            "www-data",
            wp,
            "php",
            "-r",
            'require "/var/www/html/wp-load.php"; '
            'if (!wp_mail("probe@example.invalid", "capture probe", "local only")) exit(2);',
        )
        check(
            "mail capture active before feedback",
            len(evidence()["mail_calls"]) == initial_mail_calls + 1,
        )
        report["setup_mail_calls_captured"] = initial_mail_calls + 1
        page_url = report["versions"]["page_url"]
        check("canonical fixture URL is local", page_url.startswith(origin + "/"))
        verify(origin, output, report, fixture, check, command, ASSETS, page_url)
        report["passed"] = True
        print("Real CF7 lab checks passed", flush=True)
    except Exception as error:
        report["passed"] = False
        report["error_type"] = type(error).__name__
        # Exception text from our own checks is safe; external tool exception details aren't.
        report["failed_check"] = next(
            (c["name"] for c in report["checks"] if not c["passed"]), None
        )
        raise
    finally:
        failures = []
        if local_gateway is not None:
            try:
                local_gateway.__exit__(None, None, None)
            except (RuntimeError, OSError):
                failures.append({"kind": "gateway", "name": prefix})
        for kind, name in reversed(resources):
            try:
                label = docker(
                    kind,
                    "inspect",
                    "--format",
                    '{{index .Labels "leadhive.cf7.lab"}}'
                    if kind != "container"
                    else '{{index .Config.Labels "leadhive.cf7.lab"}}',
                    name,
                )
                if label != prefix:
                    raise RuntimeError("Cleanup ownership mismatch")
                docker(kind, "rm", *(["-f"] if kind == "container" else []), name)
            except (RuntimeError, subprocess.SubprocessError, OSError):
                failures.append({"kind": kind, "name": name})
        report["cleanup_failures"] = failures
        if failures:
            report["passed"] = False
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        (output / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("Lab report: " + str(output / "report.json"), flush=True)
        if failures:
            raise RuntimeError("Lab cleanup incomplete; inspect report")


if __name__ == "__main__":
    run()
