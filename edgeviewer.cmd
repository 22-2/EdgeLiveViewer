@echo off
rem Ensure this script always runs with its own directory as the working directory.
rem Reason: Keep project-relative paths and resource lookups consistent.
pushd "%~dp0"
"C:\Users\17890\.local\bin\uv.exe" run "main.py"
popd
