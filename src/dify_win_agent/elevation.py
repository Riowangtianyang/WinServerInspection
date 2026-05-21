from collections.abc import Callable
import ctypes
import subprocess
import sys


def default_is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def default_relaunch() -> None:
    parameters = subprocess.list2cmdline(sys.argv)
    ctypes.windll.shell32.ShellExecuteW(
        None,
        "runas",
        sys.executable,
        parameters,
        None,
        1,
    )


def ensure_elevated(
    platform_name: str | None = None,
    is_admin_func: Callable[[], bool] | None = None,
    relaunch_func: Callable[[], None] | None = None,
) -> bool:
    current_platform = platform_name or sys.platform
    if current_platform != "win32":
        return False

    admin_check = is_admin_func or default_is_admin
    if admin_check():
        return False

    relaunch = relaunch_func or default_relaunch
    relaunch()
    return True