import argparse
import getpass
import os
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pyttsx3

DEVICE_SERIAL = "0300221120150447"
_speech_engine = None
_speech_disabled = False


def _announce_status(message: str) -> None:
    """Print and speak a status message without interrupting automation."""
    global _speech_engine, _speech_disabled
    print(message)
    if _speech_disabled:
        return

    try:
        if _speech_engine is None:
            _speech_engine = pyttsx3.init()
        _speech_engine.say(message)
        _speech_engine.runAndWait()
    except Exception as error:
        _speech_disabled = True
        print(f"Speech output unavailable: {error}")


def _adb_executable() -> str | None:
    """Return the ADB executable found through the system PATH."""
    return shutil.which("adb")


def _select_adb_device(adb: str) -> str:
    """Select exactly one authorized device, honoring ANDROID_SERIAL if set."""
    result = subprocess.run([adb, "devices"], check=True, capture_output=True, text=True)
    devices = {}
    for line in result.stdout.splitlines()[1:]:
        columns = line.split()
        if len(columns) >= 2:
            devices[columns[0]] = columns[1]

    authorized = [serial for serial, state in devices.items() if state == "device"]
    requested = os.environ.get("ANDROID_SERIAL")
    if requested:
        if requested not in authorized:
            raise RuntimeError(f"ANDROID_SERIAL is not connected and authorized: {requested}")
        selected = requested
    elif len(authorized) == 1:
        selected = authorized[0]
    elif not authorized:
        message = "No device connected or ADB not authorized."
        _announce_status(message)
        raise RuntimeError(message)
    else:
        raise RuntimeError(f"Multiple authorized devices found ({', '.join(authorized)}). Set ANDROID_SERIAL to choose one.")

    os.environ["ANDROID_SERIAL"] = selected
    print(f"Using ADB device: {selected}")
    return selected


def enable_usb_debugging() -> bool:
    """Enable Android USB debugging through the connected device's settings."""
    adb = _adb_executable()
    if adb is None:
        print("ADB is not installed or not available in PATH.")
        return False

    try:
        subprocess.run([adb, "devices"], check=True, capture_output=True, text=True)
        subprocess.run([adb, "shell", "settings", "put", "global", "adb_enabled", "1"], check=True, capture_output=True, text=True)
        _announce_status("USB Debugging enabled successfully.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to enable USB Debugging: {e.stderr or e}")
        return False


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
            _announce_status("No device connected or ADB not authorized.")
            return None
        return serial_number
    except subprocess.CalledProcessError as e:
        print(f"Failed to get device serial number: {e}")
        return None


def open_android_settings() -> bool:
    """Launch the main Android Settings screen on the connected device."""
    adb = _adb_executable()
    if adb is None:
        print("ADB is not installed or not available in PATH.")
        return False

    try:
        subprocess.run([adb, "shell", "am", "start", "-n", "com.android.settings/.Settings"], check=True, capture_output=True, text=True)
        _announce_status("Android Settings opened successfully.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to open Android Settings: {e.stderr or e}")
        return False


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
    if package not in packages:
        print(f"FRA fallback package is not installed: {package}")
        return None
    if package.lower().endswith(".apk"):
        print("That is an APK filename, not a package ID. Install Android SDK build-tools or enter the ID like com.example.fra.")
        return None
    return package or None


def _tap_setup_device(adb: str) -> bool:
    """Tap Setup Device after the app returns to its main menu."""
    for _ in range(10):
        subprocess.run([adb, "shell", "uiautomator", "dump", "/sdcard/fra-window.xml"], check=False, capture_output=True, text=True)
        dump = subprocess.run([adb, "exec-out", "cat", "/sdcard/fra-window.xml"], check=False, capture_output=True, text=True).stdout
        try:
            root = ET.fromstring(dump)
        except ET.ParseError:
            time.sleep(0.5)
            continue

        setup_node = next(
            (
                node for node in root.iter()
                if " ".join((node.attrib.get("text", "") or node.attrib.get("content-desc", "")).upper().split()) == "SETUP DEVICE"
            ),
            None,
        )
        if setup_node is not None:
            bounds = [int(value) for value in re.findall(r"\d+", setup_node.attrib.get("bounds", ""))]
            if len(bounds) == 4:
                left, top, right, bottom = bounds
                subprocess.run([adb, "shell", "input", "tap", str((left + right) // 2), str((top + bottom) // 2)], check=True)
                print("Setup Device tapped.")
                return _register_device(adb)
        time.sleep(0.5)

    display = subprocess.run([adb, "shell", "wm", "size"], check=False, capture_output=True, text=True).stdout
    match = re.search(r"(?:Physical|Override) size: (\d+)x(\d+)", display)
    if not match:
        print("Could not locate Setup Device or identify the device screen size.")
        return False

    width, height = (int(value) for value in match.groups())
    subprocess.run([adb, "shell", "input", "tap", str(width // 2), str(int(height * 0.628))], check=True)
    print("Setup Device tapped.")
    return _register_device(adb)


def _register_device(adb: str) -> bool:
    """Replace the Device S/N and submit the Setup Device form."""
    serial_field = None
    register_node = None
    for _ in range(10):
        subprocess.run([adb, "shell", "uiautomator", "dump", "/sdcard/fra-window.xml"], check=False, capture_output=True, text=True)
        dump = subprocess.run([adb, "exec-out", "cat", "/sdcard/fra-window.xml"], check=False, capture_output=True, text=True).stdout
        try:
            root = ET.fromstring(dump)
        except ET.ParseError:
            time.sleep(0.5)
            continue

        fields = [node for node in root.iter() if node.attrib.get("class") == "android.widget.EditText"]
        if fields:
            serial_field = fields[0]
            register_node = next(
                (
                    node for node in root.iter()
                    if " ".join((node.attrib.get("text", "") or node.attrib.get("content-desc", "")).upper().split()) == "REGISTER DEVICE"
                ),
                None,
            )
            if register_node is not None:
                break
        time.sleep(0.5)

    display = subprocess.run([adb, "shell", "wm", "size"], check=False, capture_output=True, text=True).stdout
    match = re.search(r"(?:Physical|Override) size: (\d+)x(\d+)", display)
    if not match:
        print("Could not identify the setup form or device screen size.")
        return False

    width, height = (int(value) for value in match.groups())
    if serial_field is not None:
        bounds = [int(value) for value in re.findall(r"\d+", serial_field.attrib.get("bounds", ""))]
        if len(bounds) == 4:
            left, top, right, bottom = bounds
            field_x, field_y = (left + right) // 2, (top + bottom) // 2
        else:
            field_x, field_y = width // 2, int(height * 0.385)
    else:
        field_x, field_y = width // 2, int(height * 0.385)

    subprocess.run([adb, "shell", "input", "tap", str(field_x), str(field_y)], check=True)
    subprocess.run([adb, "shell", "input", "keyevent", "KEYCODE_MOVE_END"], check=True)
    for _ in range(64):
        subprocess.run([adb, "shell", "input", "keyevent", "KEYCODE_DEL"], check=True)
    subprocess.run([adb, "shell", "input", "text", DEVICE_SERIAL], check=True)
    subprocess.run([adb, "shell", "input", "keyevent", "KEYCODE_BACK"], check=True)
    time.sleep(0.5)

    if register_node is not None:
        bounds = [int(value) for value in re.findall(r"\d+", register_node.attrib.get("bounds", ""))]
    else:
        bounds = []
    if len(bounds) == 4:
        left, top, right, bottom = bounds
        button_x, button_y = (left + right) // 2, (top + bottom) // 2
    else:
        button_x, button_y = width // 2, int(height * 0.598)

    subprocess.run([adb, "shell", "input", "tap", str(button_x), str(button_y)], check=True)
    return _wait_for_validation(adb)


def _tap_login_fields(adb: str) -> bool:
    """Enter credentials, tap REGISTER, then select Setup Device."""
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
        for y_ratio, prompt in ((0.44, "Username: "), (0.51, "Password: ")):
            subprocess.run([adb, "shell", "input", "tap", str(x), str(int(height * y_ratio))], check=True)
            value = "1234545" if prompt.startswith("User") else getpass.getpass(prompt)
            subprocess.run([adb, "shell", "input", "text", value.replace(" ", "%s")], check=True)
        subprocess.run([adb, "shell", "input", "keyevent", "KEYCODE_BACK"], check=True)
        time.sleep(1)
        subprocess.run([adb, "shell", "input", "tap", str(x), str(int(height * 0.74))], check=True)
        print("REGISTER button tapped.")
        return _tap_setup_device(adb)

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
    return _tap_setup_device(adb)


def _wait_for_validation(adb: str, timeout: float = 30) -> bool:
    """Return true only when an explicit registration confirmation is visible."""
    deadline = time.monotonic() + timeout
    success_phrases = ("device registered successfully", "registration successful", "registered successfully")
    failure_phrases = ("registration failed", "failed to register", "invalid device s/n")
    while time.monotonic() < deadline:
        subprocess.run([adb, "shell", "uiautomator", "dump", "/sdcard/fra-window.xml"], check=False, capture_output=True, text=True)
        dump = subprocess.run([adb, "exec-out", "cat", "/sdcard/fra-window.xml"], check=False, capture_output=True, text=True).stdout
        validation_text = re.sub(r"[^a-z]+", " ", dump.lower())
        if any(phrase in validation_text for phrase in success_phrases):
            _announce_status(f"Registration confirmed for S/N {DEVICE_SERIAL}.")
            return True
        if any(phrase in validation_text for phrase in failure_phrases):
            _announce_status(f"Registration failed for S/N {DEVICE_SERIAL}.")
            return False
        time.sleep(0.5)

    _announce_status(f"Registration submitted for S/N {DEVICE_SERIAL}, but the app did not expose a confirmation.")
    return False


def open_fra_application(apk_path: Path | None = None) -> bool:
    """Launch FRA and enter credentials supplied interactively by the operator."""
    adb = _adb_executable()
    if adb is None:
        print("ADB is not installed or not available in PATH.")
        return False

    package = _fra_package(adb, apk_path)
    if package is None:
        return False

    try:
        subprocess.run([adb, "shell", "monkey", "-p", package, "1"], check=True, capture_output=True, text=True)
        print(f"FRA application opened: {package}")
        return _tap_login_fields(adb)
    except subprocess.CalledProcessError as e:
        print(f"Failed to open or log in to FRA: {e.stderr or e}")
        return False


def _device_file_exists(adb: str, device_path: str) -> bool:
    """Check whether a file or directory exists at the specified device path."""
    result = subprocess.run([adb, "shell", "test", "-e", device_path], check=False, capture_output=True, text=True)
    return result.returncode == 0


def move_file_to_device(local_path: Path | None = None, device_path: str = "/sdcard/APK") -> bool:
    """Copy a local file or directory to the Android device with ADB."""
    adb = _adb_executable()
    if adb is None:
        print("ADB is not installed or not available in PATH.")
        return False

    if local_path is None:
        local_path = Path(__file__).resolve().parent.parent / "APK"

    if not local_path.exists():
        print(f"Local path does not exist: {local_path}")
        return False

    if local_path.is_dir():
        successful = True
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
                print(f"Failed to move file to device: {local_file}: {e.stderr or e}")
                successful = False
        return successful

    remote_file = device_path
    if device_path.endswith("/"):
        remote_file = f"{device_path.rstrip('/')}/{local_path.name}"

    if _device_file_exists(adb, remote_file):
        print(f"Skipping existing file on device: {remote_file}")
        return True

    try:
        subprocess.run([adb, "push", str(local_path), remote_file], check=True, capture_output=True, text=True)
        print(f"File moved to device: {remote_file}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to move file to device: {e.stderr or e}")
        return False


def install_apk(apk_path: Path | None = None) -> bool:
    """Install one APK or all APK files in a local directory on the device."""
    adb = _adb_executable()
    if adb is None:
        print("ADB is not installed or not available in PATH.")
        return False

    if apk_path is None:
        apk_path = Path(__file__).resolve().parent.parent / "APK"

    if not apk_path.exists():
        print(f"APK path does not exist: {apk_path}")
        return False

    apk_files = []
    if apk_path.is_dir():
        apk_files = sorted(apk_path.glob("*.apk"))
        if not apk_files:
            print(f"No APK files found in directory: {apk_path}")
            return False
    else:
        apk_files = [apk_path]

    installed = False
    for apk_file in apk_files:
        if not apk_file.is_file():
            continue
        try:
            subprocess.run([adb, "install", str(apk_file)], check=True, capture_output=True, text=True)
            print(f"APK installed successfully: {apk_file}")
            installed = True
        except subprocess.CalledProcessError as e:
            print(f"Failed to install APK {apk_file}: {e.stderr or e}")
            return False
    if not installed:
        print(f"No installable APK files found: {apk_path}")
    return installed


def main() -> int:
    argparse.ArgumentParser(description="Automate Android device setup and report status in the console.").parse_args()

    adb = _adb_executable()
    if adb is None:
        print("ADB is not installed or not available in PATH.")
        return 1
    try:
        _select_adb_device(adb)
    except (RuntimeError, subprocess.CalledProcessError) as e:
        print(f"Cannot start device setup: {e}")
        return 1

    if not enable_usb_debugging():
        return 1
    if not open_android_settings():
        return 1
    if not move_file_to_device():
        print("Setup stopped because file transfer did not complete.")
        return 1
    fra_apk = Path(__file__).resolve().parent.parent / "APK" / "FRA_APP2026Prod.apk"
    if not install_apk(fra_apk):
        print("Setup stopped because APK installation did not complete.")
        return 1
    if not open_fra_application(fra_apk):
        _announce_status("Setup stopped because registration was not confirmed.")
        return 1

    _announce_status(f"SETUP COMPLETE: Registration confirmed for S/N {DEVICE_SERIAL}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
