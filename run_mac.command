#!/bin/bash
cd "$(dirname "$0")"

# Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is not installed. Install it via Homebrew (brew install python) or python.org."
    read -p "Press Enter to exit..."
    exit 1
fi

# Create virtual environment if missing
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate virtual environment and install dependencies
source .venv/bin/activate
pip install --upgrade pip -q
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt -q
else
    pip install fastapi uvicorn httpx pydantic python-dotenv -q
fi

# Create .env from .env.example if missing
if [ ! -f ".env" ] && [ -f ".env.example" ]; then
    cp .env.example .env
    echo "Created .env from .env.example — please add your GEMINI_API_KEY and GEOAPIFY_API_KEY."
fi

# Open browser after a short delay and start FastAPI server
(sleep 2 && open "http://127.0.0.1:8000") &
echo "Starting Wayfinder AI at http://127.0.0.1:8000 ..."
python -m uvicorn app:app --host 127.0.0.1 --port 8000 --reload