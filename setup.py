from setuptools import setup

APP = ['claudewatch.py']
DATA_FILES = []
OPTIONS = {
    'argv_emulation': False,
    'iconfile': 'icon.png',
    'plist': {
        'CFBundleName': 'ClaudeWatch',
        'CFBundleDisplayName': 'ClaudeWatch',
        'CFBundleIdentifier': 'com.claudewatch.app',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'LSUIElement': True,  # Menu bar app, no dock icon
        'NSUserNotificationAlertStyle': 'alert',
    },
    'packages': ['rumps', 'psutil'],
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
