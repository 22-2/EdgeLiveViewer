@echo off
uv run --with nuitka --with requests==2.31.0 --with beautifulsoup4==4.12.2 --with PyQt5==5.15.9 --with zstandard==0.23.0 ^
    python -m nuitka .\main.py ^
    --standalone ^
    --enable-plugin=pyqt5 ^
    --nofollow-import-to=tkinter ^
    --windows-disable-console ^
    --output-dir=dist
