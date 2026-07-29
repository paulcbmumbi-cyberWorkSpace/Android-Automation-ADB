# Android-Automation-ADB

A small Python script to automate common Android Device Bridge (ADB) tasks for Android POS device setup.

## Features

- Detects the `adb` executable from the system `PATH`
- Enables USB debugging on a connected device
- Opens the Android Settings app on the device
- Pushes local files to the device `SDCard` or a custom device path
- Installs one or more APK files from a local directory

## Requirements

- Python 3.8+ (or later)
- Android SDK Platform Tools installed and `adb` available in `PATH`
- A connected Android device with USB debugging enabled

## Usage

Run the script directly from the repository folder:

```powershell
python auto-adb.py
```

This will:

1. Enable USB debugging on the device
2. Open Android Settings
3. Copy files from the local `APK/` folder to the device `/sdcard/APK`
4. Install APK files from the local `APK/` folder

## Custom paths

If you want to use a different local file or APK path, update the script or call the functions directly from another Python module.

## Notes

- The script skips files that already exist on the device.
- If `adb` is not available, the script prints an error message and exits.
- APK files are installed using `adb install`.
