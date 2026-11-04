@echo off
rem Fast parallel test run (skips tests/slow_tests.txt). Full suite: pytest tests
cd /d "%~dp0"
".venv\Scripts\python.exe" -m pytest tests --fast -n auto -q %*
