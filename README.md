# Android Automation ADB

A small Python automation toolkit for Android device setup, package installation, and device inventory tracking through ADB.

## Project overview

This project includes two utilities:

- `auto_adb.py` automates the initial device onboarding workflow.
- `collect_device_info.py` captures connected device model data and stores it in an Excel workbook.

## Features

### Device setup automation

- Detects the `adb` executable from `PATH`
- Validates that exactly one authorized device is connected
- Enables USB debugging on the device
- Opens Android Settings
- Pushes local files into `/sdcard/APK`
- Installs APK files from a local folder or single file
- Handles registration and status announcements with offline voice output

### Device inventory tracking

- Identifies authorized devices with `adb devices`
- Reads each device model using `getprop ro.product.model`
- Prompts for a satellite name per device
- Appends records to `device_info.xlsx` without duplicating serial numbers

## Quick start

### 1) Create a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2) Install dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 3) Run the setup automation

```powershell
python scripts/auto_adb.py
```

If you need to target a specific device when multiple devices are connected:

```powershell
$env:ANDROID_SERIAL = "your-adb-device-serial"
python scripts/auto_adb.py
```

### 4) Capture device details

```powershell
python scripts/collect_device_info.py
```

## Requirements

- Python 3.10 or newer
- Android SDK Platform Tools installed and `adb` available on `PATH`
- One or more Android devices with USB debugging authorized
- Optional: `openpyxl` for Excel workbook generation

## Project structure

```text
Android-Automation-ADB/
├── APK/                       # local APK source for automation
├── audio/                     # media and generated output files
├── scripts/
│   ├── __init__.py            # package marker for script imports
│   ├── auto_adb.py            # main Android setup automation
│   └── collect_device_info.py # device inventory workbook utility
├── .gitignore
├── pyproject.toml
├── README.md
├── requirements.txt
├── device_info.xlsx           # generated workbook (if created)
└── .venv/                     # local Python environment
```

## Notes

- The setup script exits cleanly when `adb` is missing from `PATH`.
- Existing workbook entries are preserved, and duplicate serial numbers are avoided.
- `auto_adb.py` uses `adb install` for APK installation and preserves files that already exist on the device.

## Customization

If you want to change the source APK directory, device destination path, or package selection, update the function arguments in the Python scripts or call the functions directly from another module.
