#!/bin/bash
set -euo pipefail
# ==============================================================================
# Schedule Daily Job Hunter via macOS launchd
# ==============================================================================

PLIST_NAME="com.madhav.jobhunter.plist"
LABEL="com.madhav.jobhunter"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$LAUNCH_AGENTS_DIR/$PLIST_NAME"
PROJECT_DIR="/Users/madhavjayam/job-hunter"
RUN_SCRIPT="$PROJECT_DIR/run.sh"
LOG_DIR="$PROJECT_DIR/logs"
USER_ID="$(id -u)"

# Default time: 06:30 PM (Hour: 18, Minute: 30)
HOUR=${1:-18}
MINUTE=${2:-30}

# Parse action if provided
ACTION=${1:-"install"}

if [ "$ACTION" == "uninstall" ] || [ "$ACTION" == "remove" ]; then
    echo "Uninstalling Job Hunter scheduled task..."
    launchctl bootout "gui/$USER_ID/$LABEL" 2>/dev/null || true
    rm -f "$PLIST_PATH"
    echo "✓ Scheduled task removed successfully."
    exit 0
fi

if [ "$ACTION" == "status" ]; then
    echo "Checking Job Hunter scheduled task status..."
    if [ -f "$PLIST_PATH" ]; then
        echo "✓ Job Hunter launchd service is registered at: $PLIST_PATH"
        launchctl print "gui/$USER_ID/$LABEL" >/dev/null 2>&1 \
            && echo "Note: Service loaded, waiting for scheduled trigger." \
            || echo "Note: Plist exists but service is not loaded."
    else
        echo "✗ Job Hunter is not currently scheduled."
    fi
    exit 0
fi

# Ensure directories exist
mkdir -p "$LAUNCH_AGENTS_DIR"
mkdir -p "$LOG_DIR"
chmod +x "$RUN_SCRIPT"

# If first arg is a number, use it as HOUR
if [[ "$1" =~ ^[0-9]+$ ]]; then
    HOUR=$1
    MINUTE=${2:-0}
fi

echo "========================================="
echo "   SCHEDULING DAILY JOB HUNTER RUNNER    "
echo "========================================="
echo "Scheduled Time : $(printf "%02d:%02d" $HOUR $MINUTE)"
echo "Target Script  : $RUN_SCRIPT"
echo "Stdout Log     : $LOG_DIR/daily_run.log"
echo "Stderr Log     : $LOG_DIR/daily_run_error.log"
echo "========================================="

# Generate launchd plist configuration
cat <<EOF > "$PLIST_PATH"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.madhav.jobhunter</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$RUN_SCRIPT</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$PROJECT_DIR</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>$HOUR</integer>
        <key>Minute</key>
        <integer>$MINUTE</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/daily_run.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/daily_run_error.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:$HOME/.local/bin</string>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
    </dict>
</dict>
</plist>
EOF

# Replace the current per-user LaunchAgent using the modern launchctl API.
launchctl bootout "gui/$USER_ID/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$USER_ID" "$PLIST_PATH"

echo ""
echo "✓ Successfully scheduled to run daily at $(printf "%02d:%02d" $HOUR $MINUTE)!"
echo "• Logs will be saved to: file://$LOG_DIR/daily_run.log"
echo "• To check status: ./schedule.sh status"
echo "• To remove:       ./schedule.sh uninstall"
echo "• To change time:  ./schedule.sh <HOUR_24> <MINUTE> (e.g. ./schedule.sh 10 30 for 10:30 AM)"
