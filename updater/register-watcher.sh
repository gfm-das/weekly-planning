#!/usr/bin/env bash
# updater/register-watcher.sh: makes this computer's own scheduler keep the updater watching (gfm-updater.sh watch), without administrator rights:
#   Windows  a Task Scheduler task (schtasks) that starts it every 5 minutes while this user is signed in, in a hidden window
#   Linux    two lines in this user's crontab (at start-up, and every 5 minutes)
#   Mac      a launch agent (~/Library/LaunchAgents), started at login and every 5 minutes
# The updater never runs twice (it keeps a lock), so "every 5 minutes" only means "if it is not running, start it": after an update of the
# updater itself, or if it ever stops, it is back within 5 minutes. It runs only while this user is signed in (Docker Desktop works only then).
#   bash updater/register-watcher.sh              set it up and start it
#   bash updater/register-watcher.sh --remove     take it away again
#   bash updater/register-watcher.sh --dry-run    only show what it would do
# (GFM_WATCHER_NAME: the name of the task or agent, default "GFM Weekly Planning Updater"; GFM_WATCHER_OS: pretend to be windows, mac or linux, with --dry-run.)
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/.." && pwd)
ACTION=add; DRY=no
for arg in "$@"; do case "$arg" in --remove) ACTION=remove ;; --dry-run) DRY=yes ;; *) echo "Unknown option $arg" >&2; exit 2 ;; esac; done
NAME=${GFM_WATCHER_NAME:-GFM Weekly Planning Updater}
MARK='# gfm-weekly-planning-updater'
case "${GFM_WATCHER_OS:-$(uname -s 2>/dev/null)}" in
  windows|MINGW*|MSYS*|CYGWIN*) OS=windows ;; mac|Darwin) OS=mac ;; *) OS=linux ;;
esac
say() { printf '%s\n' "$*"; }
run() { if [ "$DRY" = yes ]; then say "  would run: $*"; else "$@"; fi; }
BASH_PATH=$(command -v bash)
SCRIPT="$HERE/gfm-updater.sh"

case "$OS" in
  windows)
    # Windows wants Windows-style paths in the task, and the window hidden: a tiny script (run-hidden.vbs) starts bash without one.
    WBASH=$(cygpath -w "$BASH_PATH" 2>/dev/null || echo "$BASH_PATH"); WSCRIPT=$(cygpath -w "$SCRIPT" 2>/dev/null || echo "$SCRIPT")
    VBS="$HERE/run-hidden.vbs"; WVBS=$(cygpath -w "$VBS" 2>/dev/null || echo "$VBS")
    if [ "$ACTION" = remove ]; then
      say "Removing the scheduled task '$NAME'."
      run schtasks.exe //Delete //TN "$NAME" //F
      [ "$DRY" = yes ] || rm -f "$VBS"
    else
      say "Setting up the scheduled task '$NAME' (every 5 minutes while you are signed in)."
      if [ "$DRY" = yes ]; then say "  would write $VBS to start: \"$WBASH\" \"$WSCRIPT\" watch (hidden)"
      else printf 'CreateObject("WScript.Shell").Run """%s"" ""%s"" watch", 0, False\r\n' "$WBASH" "$WSCRIPT" > "$VBS"; fi
      run schtasks.exe //Create //F //TN "$NAME" //SC MINUTE //MO 5 //TR "wscript.exe //B \"$WVBS\""
      run schtasks.exe //Run //TN "$NAME"
    fi ;;
  mac)
    PLIST="$HOME/Library/LaunchAgents/org.weekly-planning.updater.plist"; LABEL=org.weekly-planning.updater
    if [ "$ACTION" = remove ]; then
      say "Removing the launch agent $LABEL."
      run launchctl bootout "gui/$(id -u)/$LABEL"
      [ "$DRY" = yes ] || rm -f "$PLIST"
    else
      say "Setting up the launch agent $LABEL (at login and every 5 minutes)."
      if [ "$DRY" = yes ]; then say "  would write $PLIST to run: $BASH_PATH $SCRIPT watch"
      else
        mkdir -p "$HOME/Library/LaunchAgents"
        cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$BASH_PATH</string><string>$SCRIPT</string><string>watch</string></array>
  <key>RunAtLoad</key><true/>
  <key>StartInterval</key><integer>300</integer>
  <key>WorkingDirectory</key><string>$REPO</string>
</dict></plist>
PLIST
      fi
      run launchctl bootout "gui/$(id -u)/$LABEL"
      run launchctl bootstrap "gui/$(id -u)" "$PLIST"
    fi ;;
  linux)
    CURRENT=$(crontab -l 2>/dev/null | grep -vF "$MARK" || true)
    if [ "$ACTION" = remove ]; then
      say "Removing the updater lines from this user's crontab."
      if [ "$DRY" = yes ]; then say "  would keep $(printf '%s' "$CURRENT" | grep -c .) other line(s) and drop the updater's"
      else printf '%s\n' "$CURRENT" | grep . | crontab - 2>/dev/null || crontab -r 2>/dev/null || true; fi
    else
      say "Adding two lines to this user's crontab (at start-up, and every 5 minutes)."
      LINES="@reboot \"$BASH_PATH\" \"$SCRIPT\" watch >/dev/null 2>&1 $MARK
*/5 * * * * \"$BASH_PATH\" \"$SCRIPT\" watch >/dev/null 2>&1 $MARK"
      if [ "$DRY" = yes ]; then printf '%s\n' "$LINES" | sed 's/^/  would add: /'
      else { printf '%s\n' "$CURRENT" | grep . ; printf '%s\n' "$LINES"; } | crontab -; (nohup "$BASH_PATH" "$SCRIPT" watch >/dev/null 2>&1 &) ; fi
    fi ;;
esac
say "Done."
