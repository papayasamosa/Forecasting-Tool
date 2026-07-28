@echo off
set TMP=D:\temp
set TEMP=D:\temp
echo Running tests via D: drive venv...
D:\forecasting-venv\Scripts\python.exe -m pytest tests/test_schemas.py tests/test_adapter_contract.py tests/test_benchmarking.py -v --tb=short
echo Exit code: %ERRORLEVEL%
