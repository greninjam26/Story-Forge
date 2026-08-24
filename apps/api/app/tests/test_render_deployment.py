import os
import subprocess
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[2]


def _write_command(path: Path, label: str) -> None:
    path.write_text(
        "#!/bin/sh\n"
        f'printf "{label}:%s\\n" "$*" >> "$CALL_LOG"\n',
        encoding="utf-8",
    )
    path.chmod(0o755)


def _write_failing_command(path: Path, exit_code: int) -> None:
    path.write_text(
        "#!/bin/sh\n"
        'printf "alembic:%s\\n" "$*" >> "$CALL_LOG"\n'
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def test_render_start_migrates_before_starting_api(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_command(bin_dir / "alembic", "alembic")
    _write_command(bin_dir / "uvicorn", "uvicorn")
    call_log = tmp_path / "calls.log"
    environment = {
        **os.environ,
        "CALL_LOG": str(call_log),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "PORT": "12345",
    }

    subprocess.run(
        ["sh", str(API_ROOT / "scripts" / "start_render.sh")],
        cwd=API_ROOT,
        env=environment,
        check=True,
    )

    assert call_log.read_text(encoding="utf-8").splitlines() == [
        "alembic:upgrade head",
        "uvicorn:app.main:app --host 0.0.0.0 --port 12345",
    ]


def test_render_start_stops_when_migration_fails(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_failing_command(bin_dir / "alembic", exit_code=23)
    _write_command(bin_dir / "uvicorn", "uvicorn")
    call_log = tmp_path / "calls.log"
    environment = {
        **os.environ,
        "CALL_LOG": str(call_log),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
    }

    result = subprocess.run(
        ["sh", str(API_ROOT / "scripts" / "start_render.sh")],
        cwd=API_ROOT,
        env=environment,
        check=False,
    )

    assert result.returncode == 23
    assert call_log.read_text(encoding="utf-8").splitlines() == [
        "alembic:upgrade head",
    ]
