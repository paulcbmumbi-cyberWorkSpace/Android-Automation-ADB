import shutil
import subprocess
from pathlib import Path


def _adb_executable() -> str | None:
    return shutil.which("adb")


def enable_usb_debugging() -> None:
    adb = _adb_executable()
    if adb is None:
        print("ADB is not installed or not available in PATH.")
        return

    try:
        subprocess.run([adb, "devices"], check=True, capture_output=True, text=True)
        subprocess.run([adb, "shell", "settings", "put", "global", "adb_enabled", "1"], check=True, capture_output=True, text=True)
        print("USB Debugging enabled successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Failed to enable USB Debugging: {e}")


def open_android_settings() -> None:
    adb = _adb_executable()
    if adb is None:
        print("ADB is not installed or not available in PATH.")
        return

    try:
        subprocess.run([adb, "shell", "am", "start", "-n", "com.android.settings/.Settings"], check=True, capture_output=True, text=True)
        print("Android Settings opened successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Failed to open Android Settings: {e}")


def _device_file_exists(adb: str, device_path: str) -> bool:
    result = subprocess.run([adb, "shell", "test", "-e", device_path], check=False, capture_output=True, text=True)
    return result.returncode == 0


def move_file_to_device(local_path: Path | None = None, device_path: str = "/sdcard/APK") -> None:
    adb = _adb_executable()
    if adb is None:
        print("ADB is not installed or not available in PATH.")
        return

    if local_path is None:
        local_path = Path(__file__).resolve().parent / "APK"

    if not local_path.exists():
        print(f"Local path does not exist: {local_path}")
        return

    if local_path.is_dir():
        for local_file in sorted(local_path.iterdir()):
            if not local_file.is_file():
                continue

            remote_file = f"{device_path.rstrip('/')}/{local_file.name}"
            if _device_file_exists(adb, remote_file):
                print(f"Skipping existing file on device: {remote_file}")
                continue

            try:
                subprocess.run([adb, "push", str(local_file), remote_file], check=True, capture_output=True, text=True)
                print(f"File moved to device: {remote_file}")
            except subprocess.CalledProcessError as e:
                print(f"Failed to move file to device: {local_file}: {e}")
    else:
        remote_file = device_path
        if device_path.endswith("/"):
            remote_file = f"{device_path.rstrip('/')}/{local_path.name}"

        if _device_file_exists(adb, remote_file):
            print(f"Skipping existing file on device: {remote_file}")
            return

        try:
            subprocess.run([adb, "push", str(local_path), remote_file], check=True, capture_output=True, text=True)
            print(f"File moved to device: {remote_file}")
        except subprocess.CalledProcessError as e:
            print(f"Failed to move file to device: {e}")


def install_apk(apk_path: Path | None = None) -> None:
    adb = _adb_executable()
    if adb is None:
        print("ADB is not installed or not available in PATH.")
        return

    if apk_path is None:
        apk_path = Path(__file__).resolve().parent / "APK"

    if not apk_path.exists():
        print(f"APK path does not exist: {apk_path}")
        return

    apk_files = []
    if apk_path.is_dir():
        apk_files = sorted(apk_path.glob("*.apk"))
        if not apk_files:
            print(f"No APK files found in directory: {apk_path}")
            return
    else:
        apk_files = [apk_path]

    for apk_file in apk_files:
        if not apk_file.is_file():
            continue
        try:
            subprocess.run([adb, "install", str(apk_file)], check=True, capture_output=True, text=True)
            print(f"APK installed successfully: {apk_file}")
        except subprocess.CalledProcessError as e:
            print(f"Failed to install APK {apk_file}: {e}\n{e.stderr}")

if __name__ == "__main__":
    enable_usb_debugging()
    open_android_settings()
    move_file_to_device()
    install_apk()

  

    