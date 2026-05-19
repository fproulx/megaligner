#!/bin/sh

cd "$(dirname "$0")" || exit 1

clear
printf '%s\n' "Megaligner"
printf '%s\n' "This window shows progress. The app will ask you to choose the DOCX folder and the TMX output file."
printf '%s\n' ""

RUNNER=native sh scripts/make_align.sh
status=$?

if command -v osascript >/dev/null 2>&1; then
  if [ "$status" -eq 0 ]; then
    osascript -e 'display dialog "Megaligner finished." buttons {"OK"} default button "OK" with icon note' >/dev/null 2>&1 || true
  else
    osascript -e 'display dialog "Megaligner stopped or failed. Check the Terminal window for details." buttons {"OK"} default button "OK" with icon stop' >/dev/null 2>&1 || true
  fi
fi

printf '%s\n' ""
printf '%s\n' "You can close this window."
exit "$status"
