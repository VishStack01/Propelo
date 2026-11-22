"""Official lists of employers that have hired people on work visas, for countries that publish one.

    careeros registers --out feed [--only us,ca,ie]

Each list is written as `name,n` (employer, how many approvals or permits the list shows) and read by the scan the
same way as the UK and Dutch registers (see sponsors.py):

  us-sponsors.csv  United States. Department of Labor, Labor Condition Application disclosure data: employers with
                   certified H-1B applications in the latest quarters published. Filing one is a required step before
                   an H-1B petition, so it shows the employer has sponsored, not that it will for a given role.
  ca-sponsors.csv  Canada. Employment and Social Development Canada, employers issued a positive Labour Market Impact
                   Assessment in the last four quarters (Open Government Licence - Canada).
  ie-sponsors.csv  Ireland. Department of Enterprise, Tourism and Employment, employment permits issued to companies
                   this year.

Countries without a public list (Australia, New Zealand in bulk, Singapore, Sweden, Germany) get the posting's own
words only; nothing is guessed. The files are large spreadsheets, so this runs weekly in its own workflow and needs
`openpyxl` for the Excel ones. Every fetch fails closed: an unreadable or tiny result keeps the old file.
"""

from __future__ import annotations

import csv
import io
import json
import re
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable, Iterator
from urllib.parse import urljoin

UA = "careeros (+https://github.com/VishStack01/Propelo; reads public government lists once a week)"
US_PAGE = "https://www.dol.gov/agencies/eta/foreign-labor/performance"
CA_API = "https://open.canada.ca/data/api/action/package_show?id=90fed587-1364-4f33-a9ee-208181dc0b97"
IE_PAGES = ["https://www.gov.ie/en/department-of-enterprise-tourism-and-employment/publications/employment-permit-statistics-{year}/",
            "https://enterprise.gov.ie/en/publications/employment-permit-statistics-{year}.html"]
MIN_ROWS = {"us": 5000, "ca": 1000, "ie": 300}


def _get(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(60 * 1024 * 1024)


def _download(url: str, dest: Path, timeout: int = 600, limit: int = 600 * 1024 * 1024) -> Path:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    size = 0
    with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise OSError(f"{url} is larger than {limit // 1024 // 1024} MB")
            f.write(chunk)
    return dest


def rows_of(path: Path) -> Iterator[list[str]]:
    """Rows of a spreadsheet as lists of text, whether it is Excel (.xlsx) or CSV. Every sheet of a workbook is read."""
    with open(path, "rb") as f:
        head = f.read(4)
    if head[:2] == b"PK":
        try:
            import openpyxl
        except ImportError as e:  # pragma: no cover - the registers workflow installs it
            raise OSError("Reading Excel files needs openpyxl (pip install openpyxl)") from e
        with open(path, "rb") as f:  # as a file object: openpyxl refuses paths that don't end in .xlsx
            wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
            try:
                for ws in wb.worksheets:
                    for row in ws.iter_rows(values_only=True):
                        yield ["" if v is None else str(v).strip() for v in row]
            finally:
                wb.close()
        return
    if head[:4] == b"%PDF":
        raise OSError("The list is a PDF, which this reader doesn't parse")
    text = path.read_bytes().decode("utf-8-sig", errors="replace")
    for row in csv.reader(io.StringIO(text)):
        yield [c.strip() for c in row]


def tally(rows: Iterator[list[str]], name_keys: tuple[str, ...], count_keys: tuple[str, ...] = (),
          keep: Callable[[dict], bool] | None = None, need: tuple[str, ...] = (), log=None) -> dict[str, int]:
    """{employer: total} from rows with a header somewhere near the top. The header is the first row with a cell
    matching one of `name_keys`; `count_keys` names a column to add up (else each row counts one); `keep` filters
    rows given as {header: value}; `need` lists other headers `keep` uses."""
    out: dict[str, int] = {}
    cols: dict[str, int] | None = None
    name_i = count_i = None
    for n, row in enumerate(rows):
        if cols is None:
            low = [c.lower() for c in row]
            hit = next((i for i, c in enumerate(low) if any(re.fullmatch(k, c) or re.search(k, c) for k in name_keys) and len(c) < 60), None)
            if hit is not None and len([c for c in low if c]) >= 2:
                cols = {c: i for i, c in enumerate(low) if c}
                name_i = hit
                count_i = next((i for i, c in enumerate(low) if any(re.search(k, c) for k in count_keys)), None) if count_keys else None
                if log:
                    log(f"    header (row {n + 1}): {[c for c in row if c][:20]}; employer column {name_i + 1}, "
                        f"count column {count_i + 1 if count_i is not None else 'none (each row counts one)'}")
            elif n > 40:
                raise OSError("No header row with an employer column in the first 40 rows")
            continue
        if name_i >= len(row):
            continue
        name = re.sub(r"\s+", " ", row[name_i]).strip()
        if not name or name.lower() in ("total", "grand total") or len(name) > 160:
            continue
        if keep is not None:
            rec = {k: (row[i] if i < len(row) else "") for k, i in cols.items() if not need or k in need}
            if not keep(rec):
                continue
        add = 1
        if count_i is not None and count_i < len(row):
            try:
                add = int(float(row[count_i].replace(",", "") or 0))
            except ValueError:
                add = 0
        if add > 0:
            out[name] = out.get(name, 0) + add
    if cols is None:
        raise OSError("No header row with an employer column")
    return out


def _write(dest: Path, counts: dict[str, int], kind: str) -> int:
    if len(counts) < MIN_ROWS[kind]:
        raise OSError(f"The {kind.upper()} list looks wrong ({len(counts)} employers); keeping the old file")
    with open(dest, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["name", "n"])
        w.writerows(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower())))
    return len(counts)


def us_links(page: str) -> list[str]:
    """LCA disclosure files on the Department of Labor performance page, newest first."""
    found = {(int(fy), int(q)): urljoin(US_PAGE, href)
             for href, fy, q in re.findall(r'href="([^"]*LCA_Disclosure_Data_FY(\d{4})_Q(\d)\.xlsx)"', page, re.I)}
    return [found[k] for k in sorted(found, reverse=True)]


def fetch_us(dest: str | Path, files: int = 2, log=print) -> int:
    links = us_links(_get(US_PAGE).decode("utf-8", errors="replace"))[:files]
    if not links:
        raise OSError("No LCA disclosure file is linked on the Department of Labor page")
    counts: dict[str, int] = {}
    with tempfile.TemporaryDirectory(prefix="propelo-lca-") as tmp:
        for i, url in enumerate(links):
            log(f"  reading {url}")
            path = _download(url, Path(tmp) / f"lca{i}.xlsx")
            part = tally(rows_of(path), (r"employer_name",), keep=lambda r: r.get("case_status", "").lower().startswith("certified")
                         and r.get("visa_class", "").upper().startswith("H-1B"), need=("case_status", "visa_class"))
            for k, v in part.items():
                counts[k] = counts.get(k, 0) + v
            path.unlink()
    return _write(Path(dest), counts, "us")


def ca_links(api_json: str) -> list[str]:
    """English positive-LMIA employer files from the open data catalogue, newest quarter first."""
    data = json.loads(api_json)
    found = {}
    for r in ((data.get("result") or {}).get("resources") or []):
        url = str(r.get("url") or "")
        m = re.search(r"(\d{4})\s*q(\d)[^/]*pos[^/]*_en\.(?:xlsx|csv)$", url, re.I)
        if m:
            found[(int(m.group(1)), int(m.group(2)))] = url
    return [found[k] for k in sorted(found, reverse=True)]


def fetch_ca(dest: str | Path, quarters: int = 4, log=print) -> int:
    links = ca_links(_get(CA_API).decode("utf-8", errors="replace"))[:quarters]
    if not links:
        raise OSError("No positive LMIA employer file found in the open data catalogue")
    counts: dict[str, int] = {}
    with tempfile.TemporaryDirectory(prefix="propelo-lmia-") as tmp:
        for i, url in enumerate(links):
            log(f"  reading {url}")
            path = _download(url, Path(tmp) / f"lmia{i}")
            for k, v in tally(rows_of(path), (r"^employer$", r"employer"), (r"approved positions", r"positions"), log=log if i == 0 else None).items():
                counts[k] = counts.get(k, 0) + v
    return _write(Path(dest), counts, "ca")


def ie_link(page: str, base: str) -> str:
    """The "permits issued to companies" file on the statistics page: the download link nearest those words."""
    best = ""
    for m in re.finditer(r'href="([^"]+)"', page):
        href = m.group(1)
        around = page[max(0, m.start() - 500):m.end() + 300].lower()
        if not re.search(r"\.(xlsx|xls|csv)(\?|$)|assets\.gov\.ie|/publication-files/", href, re.I) or href.lower().endswith(".pdf"):
            continue
        if "compan" in href.lower():
            return urljoin(base, href)
        if "compan" in around and not best:
            best = urljoin(base, href)
    return best


def fetch_ie(dest: str | Path, year: int | None = None, log=print) -> int:
    from datetime import datetime, timezone
    year = year or datetime.now(timezone.utc).year
    last: Exception | None = None
    for y in (year, year - 1):  # January: this year's file may not exist yet
        for tpl in IE_PAGES:
            url = tpl.format(year=y)
            try:
                link = ie_link(_get(url).decode("utf-8", errors="replace"), url)
                if not link:
                    raise OSError(f"No companies file linked on {url}")
                log(f"  reading {link}")
                with tempfile.TemporaryDirectory(prefix="propelo-ie-") as tmp:
                    path = _download(link, Path(tmp) / "ie")
                    counts = tally(rows_of(path), (r"employer", r"company", r"^name$"), (r"total", r"issued", r"permits", r"^" + str(y) + r"$"), log=log)
                return _write(Path(dest), counts, "ie")
            except (OSError, ValueError) as e:
                last = e
                log(f"  {url}: {e}")
    raise OSError(f"Irish permits list not updated: {last}")


FETCHERS = {"us": ("us-sponsors.csv", fetch_us), "ca": ("ca-sponsors.csv", fetch_ca), "ie": ("ie-sponsors.csv", fetch_ie)}


def run(out_dir: str | Path, only: list[str] | None = None, log=print) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    result = {}
    for kind, (fname, fn) in FETCHERS.items():
        if only and kind not in only:
            continue
        try:
            n = fn(out / fname, log=log)
            result[kind] = n
            log(f"{kind.upper()} register: {n} employers -> {out / fname}")
        except Exception as e:  # one list failing never stops the others
            result[kind] = f"not updated: {type(e).__name__}: {e}"[:300]
            log(f"{kind.upper()} register {result[kind]}")
    return result
