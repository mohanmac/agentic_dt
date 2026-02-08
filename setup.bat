@echo off
echo ========================================
echo DayTradingPaperBot - Quick Setup
echo ========================================
echo.

echo Step 1: Creating .env file from template...
if not exist .env (
    copy .env.example .env
    echo .env file created. Please edit it with your Zerodha credentials.
) else (
    echo .env file already exists.
)
echo.

echo Step 2: Creating virtual environment...
if not exist venv (
    python -m venv venv
    echo Virtual environment created.
) else (
    echo Virtual environment already exists.
)
echo.

echo Step 3: Activating virtual environment...
call venv\Scripts\activate.bat
echo.

echo Step 4: Installing dependencies...
pip install -r requirements.txt
echo.

echo Step 5: Adding pytest for testing...
pip install pytest
echo.

echo ========================================
echo Setup Complete!
echo ========================================
echo.
echo Next steps:
echo 1. Edit .env file with your Zerodha API credentials
echo 2. Start Ollama: ollama serve
echo 3. Pull model: ollama pull qwen2.5:7b
echo 4. Authenticate: python -m app auth
echo 5. Run paper trading: python -m app run --paper
echo 6. Launch dashboard: python -m app dashboard
echo.
echo For help: python -m app --help
echo.
pause
