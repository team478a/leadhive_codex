"""Read-only database readiness before fixture installation, no secret output."""

import time

PROBE = "mysqli_report(MYSQLI_REPORT_OFF); $h=explode(':',getenv('WORDPRESS_DB_HOST')); try {$c=@new mysqli($h[0],getenv('WORDPRESS_DB_USER'),getenv('WORDPRESS_DB_PASSWORD'),getenv('WORDPRESS_DB_NAME'),3306); exit($c->connect_errno ? 2 : 0);} catch(Throwable $e) {exit(2);}"


def wait_for_database(docker, container, *, attempts=30):
    for attempt in range(attempts):
        try:
            docker("exec", container, "php", "-r", PROBE, timeout=10)
            return
        except RuntimeError:
            if attempt + 1 < attempts:
                time.sleep(1)
    raise RuntimeError("Isolated lab database did not become ready")
