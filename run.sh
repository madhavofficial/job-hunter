#!/bin/bash
set -e

# Resolve script directory
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "========================================="
echo "        DAILY JOB HUNTER PIPELINE        "
echo "========================================="

# Check virtual environment
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    uv venv
fi

# Activate environment
source .venv/bin/activate
export PYTHONUNBUFFERED=1
export JOB_HUNTER_RUN_STARTED_UTC="$(date -u '+%Y-%m-%d %H:%M:%S')"

# Execute step 1: Scraping/Collection
echo "Step 1: Discovering direct ATS listings..."
python ats_collector.py

echo "Step 2: Running Job Collector..."
python collector.py 15 72

# Execute step 3: Matching
echo "Step 3: Running Resume Matcher..."
python matcher.py

# Execute step 4: Generating Dashboard
echo "Step 4: Generating Dashboard..."
python dashboard.py

echo "========================================="
echo "Pipeline execution finished successfully!"
echo "View your dashboard at: file://$DIR/dashboard.md"
echo "========================================="
