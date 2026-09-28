import getpass
import os
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path


def _adb_executable() -> str | None:
    """Return the ADB executable found through the system PATH."""
    return shutil.which("adb")


def enable_usb_debugging() -> None:
    """Enable Android USB debugging through the connected device's settings."""
    adb = _adb_executable()
    if adb is None:
        print("ADB is not installed or not available in PATH.")
        return

    try:
        # Confirm communication before attempting to change the device setting.
        subprocess.run([adb, "devices"], check=True, capture_output=True, text=True)
        subprocess.run([adb, "shell", "settings", "put", "global", "adb_enabled", "1"], check=True, capture_output=True, text=True)
        print("USB Debugging enabled successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Failed to enable USB Debugging: {e}")


def get_device_serial() -> str | None:
    """Return the connected device serial number, or None when unavailable."""
    adb = _adb_executable()
    if adb is None:
        print("ADB is not installed or not available in PATH.")
        return None

    try:
        result = subprocess.run([adb, "get-serialno"], check=True, capture_output=True, text=True)
        serial_number = result.stdout.strip()
        if serial_number == "unknown":
            print("No device connected or ADB not authorized.")
            return None
        return serial_number
    except subprocess.CalledProcessError as e:
        print(f"Failed to get device serial number: {e}")
        return None


def open_android_settings() -> None:
    """Launch the main Android Settings screen on the connected device."""
    adb = _adb_executable()
    if adb is None:
        print("ADB is not installed or not available in PATH.")
        return

    try:
        subprocess.run([adb, "shell", "am", "start", "-n", "com.android.settings/.Settings"], check=True, capture_output=True, text=True)
        print("Android Settings opened successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Failed to open Android Settings: {e}")


def _aapt_executable() -> str | None:
    """Find aapt on PATH or in the installed Android SDK build-tools."""
    aapt = shutil.which("aapt")
    if aapt:
        return aapt

    sdk_roots = [os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT")]
    local_sdk = os.environ.get("LOCALAPPDATA")
    if local_sdk:
        sdk_roots.append(str(Path(local_sdk) / "Android" / "Sdk"))

    candidates = []
    for sdk_root in sdk_roots:
        if sdk_root:
            candidates.extend(Path(sdk_root).glob("build-tools/*/aapt.exe"))
    return str(sorted(candidates)[-1]) if candidates else None


def _apk_package_name(apk_path: Path | None) -> str | None:
    """Read an APK package ID with the Android SDK build-tools when available."""
    aapt = _aapt_executable()
    if aapt is None or apk_path is None:
        return None

    result = subprocess.run([aapt, "dump", "badging", str(apk_path)], check=False, capture_output=True, text=True)
    match = re.search(r"package: name='([^']+)'", result.stdout)
    return match.group(1) if match else None


def _fra_package(adb: str, apk_path: Path | None = None) -> str | None:
    """Find the installed FRA package, or use the package ID from the APK."""
    configured_package = os.environ.get("FRA_PACKAGE")

    result = subprocess.run([adb, "shell", "pm", "list", "packages"], check=False, capture_output=True, text=True)
    packages = [line.removeprefix("package:").strip() for line in result.stdout.splitlines()]

    if configured_package:
        if configured_package in packages:
            return configured_package
        print(f"FRA_PACKAGE is not installed: {configured_package}")
        return None

    apk_package = _apk_package_name(apk_path)
    if apk_package in packages:
        return apk_package

    matches = [package for package in packages if "fra" in package.lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        print(f"Multiple FRA packages found. Set FRA_PACKAGE to choose one: {', '.join(matches)}")
    else:
        print("FRA package was not found in installed packages.")
    package = "com.cropmanagement.zra"
    if package.lower().endswith(".apk"):
        print("That is an APK filename, not a package ID. Install Android SDK build-tools or enter the ID like com.example.fra.")
        return None
    return package or None


def _tap_login_fields(adb: str) -> bool:
    """Enter credentials and tap the lower REGISTER button."""
    for _ in range(10):
        subprocess.run([adb, "shell", "uiautomator", "dump", "/sdcard/fra-window.xml"], check=False, capture_output=True, text=True)
        dump = subprocess.run([adb, "exec-out", "cat", "/sdcard/fra-window.xml"], check=False, capture_output=True, text=True).stdout
        try:
            root = ET.fromstring(dump)
        except ET.ParseError:
            time.sleep(0.5)
            continue

        fields = [
            node for node in root.iter()
            if node.attrib.get("class") == "android.widget.EditText"
        ]
        register_node = next(
            (node for node in root.iter() if node.attrib.get("text", "").strip().upper() == "REGISTER"),
            None,
        )
        if len(fields) >= 2 and register_node is not None:
            break
        time.sleep(0.5)
    else:
        display = subprocess.run([adb, "shell", "wm", "size"], check=False, capture_output=True, text=True).stdout
        match = re.search(r"Physical size: (\d+)x(\d+)", display)
        if not match:
            print("Could not identify the FRA login fields or device screen size.")
            return False

        width, height = (int(value) for value in match.groups())
        x = width // 2
        # FRA's WebView does not expose its HTML inputs to UIAutomator.
        for y_ratio, prompt in ((0.44, "Username: "), (0.51, "Password: ")):
            subprocess.run([adb, "shell", "input", "tap", str(x), str(int(height * y_ratio))], check=True)
            value = "22/7p@ul" if prompt.startswith("User") else getpass.getpass(prompt)
            subprocess.run([adb, "shell", "input", "text", value.replace(" ", "%s")], check=True)
        subprocess.run([adb, "shell", "input", "keyevent", "KEYCODE_BACK"], check=True)
        time.sleep(1)
        subprocess.run([adb, "shell", "input", "tap", str(x), str(int(height * 0.74))], check=True)
        print("REGISTER button tapped.")
        return True

    for index, field in enumerate(fields[:2]):
        left, top, right, bottom = (int(value) for value in re.findall(r"\d+", field.attrib["bounds"]))
        x = (int(left) + int(right)) // 2
        y = (int(top) + int(bottom)) // 2
        subprocess.run([adb, "shell", "input", "tap", str(x), str(y)], check=True)
        value = "mumbipaul88@gmail.com" if index == 0 else getpass.getpass("Password: ")
        subprocess.run([adb, "shell", "input", "text", value.replace(" ", "%s")], check=True)

    subprocess.run([adb, "shell", "input", "keyevent", "KEYCODE_BACK"], check=True)
    time.sleep(1)
    left, top, right, bottom = (int(value) for value in re.findall(r"\d+", register_node.attrib["bounds"]))
    subprocess.run([adb, "shell", "input", "tap", str((left + right) // 2), str((top + bottom) // 2)], check=True)
    print("REGISTER button tapped.")
    return True


def _wait_for_validation(adb: str, timeout: float = 30) -> None:
    """Wait for validation when visible, without treating an inaccessible dialog as failure."""
    deadline = time.monotonic() + timeout
    appeared = False
    time.sleep(0.5)
    while time.monotonic() < deadline:
        subprocess.run([adb, "shell", "uiautomator", "dump", "/sdcard/fra-window.xml"], check=False, capture_output=True, text=True)
        dump = subprocess.run([adb, "exec-out", "cat", "/sdcard/fra-window.xml"], check=False, capture_output=True, text=True).stdout
        validation_text = re.sub(r"[^a-z]+", " ", dump.lower())
        validation_visible = (
            "validating details" in validation_text
            or "please wait" in validation_text
            or "validatingdetails" in validation_text.replace(" ", "")
        )
        if validation_visible:
            if not appeared:
                print("Validating Details... Please Wait......")
                appeared = True
        elif appeared:
            print("FRA validation finished.")
            return
        time.sleep(0.5)

    if appeared:
        print("FRA validation is still in progress after 30 seconds.")
    else:
        print("Credentials submitted. FRA validation dialog was not exposed by the device UI.")


def open_fra_application(apk_path: Path | None = None) -> None:
    """Launch FRA and enter credentials supplied interactively by the operator."""
    adb = _adb_executable()
    if adb is None:
        print("ADB is not installed or not available in PATH.")
        return

    package = _fra_package(adb, apk_path)
    if package is None:
        return

    try:
        subprocess.run([adb, "shell", "monkey", "-p", package, "1"], check=True, capture_output=True, text=True)
        print(f"FRA application opened: {package}")
        _tap_login_fields(adb)
    except subprocess.CalledProcessError as e:
        print(f"Failed to open or log in to FRA: {e}")


def _device_file_exists(adb: str, device_path: str) -> bool:
    """Check whether a file or directory exists at the specified device path."""
    result = subprocess.run([adb, "shell", "test", "-e", device_path], check=False, capture_output=True, text=True)
    return result.returncode == 0


def move_file_to_device(local_path: Path | None = None, device_path: str = "/sdcard/APK") -> None:
    """Copy a local file or directory to the Android device with ADB."""
    adb = _adb_executable()
    if adb is None:
        print("ADB is not installed or not available in PATH.")
        return

    if local_path is None:
        # Use the APK folder at the project root when no source is provided.
        local_path = Path(__file__).resolve().parent.parent / "APK"

    if not local_path.exists():
        print(f"Local path does not exist: {local_path}")
        return

    if local_path.is_dir():
        # Push files individually so existing remote files can be preserved.
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
    """Install one APK or all APK files in a local directory on the device."""
    adb = _adb_executable()
    if adb is None:
        print("ADB is not installed or not available in PATH.")
        return

    if apk_path is None:
        # Use the APK folder at the project root when no source is provided.
        apk_path = Path(__file__).resolve().parent.parent / "APK"

    if not apk_path.exists():
        print(f"APK path does not exist: {apk_path}")
        return

    apk_files = []
    if apk_path.is_dir():
        # Keep installation order predictable when a directory is supplied.
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
    fra_apk = Path(__file__).resolve().parent.parent / "APK" / "FRA_APP2026Prod.apk"
    install_apk(fra_apk)
    open_fra_application(fra_apk)



  

    