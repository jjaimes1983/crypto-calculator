#!/bin/bash
# Double-click this file in Finder to start Crypto Calculator.
# First run installs dependencies and can take a couple of minutes -
# this window stays open and tells you what's happening at each step.
cd "$(dirname "$0")"

echo "== Crypto Calculator =="
echo ""

fail() {
  echo ""
  echo "$1"
  echo ""
  read -p "Press Enter to close this window..."
  exit 1
}

if ! command -v python3 >/dev/null 2>&1; then
  fail "Python 3 isn't installed (or not found). Open Terminal and run 'python3 --version' - if macOS offers to install command line developer tools, click Install, wait for it to finish, then double-click this file again."
fi

echo "Using $(python3 --version)"

if [ ! -d "venv" ]; then
  echo "First-time setup: creating a virtual environment..."
  python3 -m venv venv || fail "Couldn't create the virtual environment - see the error above."
fi

source venv/bin/activate

# An old pip bundled with the venv can fail to resolve perfectly good
# packages ("no matching distribution") just because its dependency
# resolver is outdated - upgrade it before installing anything else.
pip install -q --upgrade pip

echo "Checking/installing dependencies (first time can take a couple of minutes)..."
pip install -q -r requirements.txt || fail "Dependency install failed - see the error above (often means no internet connection right now)."

if [ ! -f "data/crypto.db" ]; then
  echo "Setting up the database..."
  python -m backend.init_db || fail "Database setup failed - see the error above."
fi

echo "Starting the server..."
uvicorn backend.main:app --port 8000 &
SERVER_PID=$!

# Don't open the browser until the server is actually answering - avoids
# "Safari can't connect" when startup takes longer than a fixed pause.
READY=0
for i in $(seq 1 60); do
  if curl -s -o /dev/null "http://localhost:8000/"; then
    READY=1
    break
  fi
  sleep 1
done

if [ "$READY" = "1" ]; then
  open "http://localhost:8000"
else
  echo "The server didn't respond after 60 seconds - check the messages above for an error."
fi

echo ""
echo "Server is running. Close this window (or press Ctrl+C) to stop it."
wait $SERVER_PID
