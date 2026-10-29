"""Import the official swisstopo CSV ZIP into the offline canton lookup.

Download the CSV (WGS84) asset linked by the source below, then run:
  python scripts/update_swiss_localities.py archive.zip --snapshot-date YYYY-MM-DD
The snapshot date is the STAC item's properties.datetime, not the download date.
"""

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
from zipfile import ZipFile

SOURCE = "https://www.swisstopo.admin.ch/en/official-directory-of-towns-and-cities"
ASSET = (
    "https://data.geo.admin.ch/ch.swisstopo-vd.ortschaftenverzeichnis_plz/"
    "ortschaftenverzeichnis_plz/ortschaftenverzeichnis_plz_4326.csv.zip"
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--snapshot-date", required=True)
    args = parser.parse_args()
    with ZipFile(args.archive) as archive:
        names = [name for name in archive.namelist() if name.endswith(".csv")]
        if len(names) != 1:
            raise ValueError("Expected one swisstopo CSV in the archive")
        rows = csv.DictReader(
            io.StringIO(archive.read(names[0]).decode("utf-8-sig")), delimiter=";"
        )
        localities = sorted(
            {
                (
                    row["Ortschaftsname"],
                    row["PLZ4"],
                    row["Gemeindename"],
                    row["Kantonskürzel"],
                )
                for row in rows
                if row["Kantonskürzel"] and row["Kantonskürzel"] != "FL"
            }
        )
    metadata = {
        "source": SOURCE,
        "attribution": "Source: Federal Office of Topography swisstopo",
        "asset": ASSET,
        "snapshotDate": args.snapshot_date,
        "archiveSha256": hashlib.sha256(args.archive.read_bytes()).hexdigest(),
        "columns": ["locality", "postcode", "municipality", "canton"],
    }
    # One record per line keeps updates reviewable without a large expanded JSON file.
    output = json.dumps(metadata, ensure_ascii=False, indent=2)[:-2]
    output += ',\n  "rows": [\n'
    output += ",\n".join(
        "    " + json.dumps(row, ensure_ascii=False) for row in localities
    )
    output += "\n  ]\n}\n"
    destination = (
        Path(__file__).resolve().parents[1] / "apps/api/app/data/swiss_localities.json"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(output, encoding="utf-8")
    print(f"Imported {len(localities)} locality/postcode/municipality/canton records")


if __name__ == "__main__":
    main()
