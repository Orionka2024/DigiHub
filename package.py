from __future__ import annotations

import io
import json
import zipfile

from models import FilingSnapshot
from registry import TaxonomyRelease


def create_report_package(snapshot: FilingSnapshot, taxonomy: TaxonomyRelease, ixbrl: bytes) -> bytes:
    filename = f"{snapshot.kvk_number}-{snapshot.period_end.year}.xhtml"
    # Report Packages 1.0 (2023 REC): a single top-level directory and
    # reportPackage.json identify an unconstrained .zip report package.
    root = f"{snapshot.kvk_number}-{snapshot.period_end.year}"
    manifest = {"documentInfo": {"documentType": "https://xbrl.org/report-package/2023"}}
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in ((f"{root}/META-INF/reportPackage.json", json.dumps(manifest, sort_keys=True)),
                              (f"{root}/reports/{filename}", ixbrl)):
            item = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = 0o100644 << 16
            archive.writestr(item, content)
    return output.getvalue()
