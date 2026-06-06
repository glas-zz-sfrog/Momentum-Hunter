from __future__ import annotations

import argparse

from momentum_hunter.quarantine import quarantine_raw_capture


def main() -> int:
    parser = argparse.ArgumentParser(description="Quarantine a Momentum Hunter raw capture.")
    parser.add_argument("capture_date", help="Capture date in YYYY-MM-DD format.")
    parser.add_argument("session", choices=["morning", "evening", "manual"], help="Capture session to quarantine.")
    parser.add_argument("--reason", required=True, help="Recovery note reason.")
    args = parser.parse_args()

    result = quarantine_raw_capture(args.capture_date, args.session, reason=args.reason)
    print(f"Quarantined {args.capture_date} {args.session}.")
    print(f"Quarantine Dir: {result.quarantine_dir}")
    print(f"Recovery Note: {result.note_path}")
    print(f"Files Moved: {len(result.moved_paths)}")
    print(f"Manifest Records Moved: {result.manifest_records_moved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
