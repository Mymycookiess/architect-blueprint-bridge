
from __future__ import annotations
from zipfile import ZipFile
import xml.etree.ElementTree as ET
import re

NS = {"m":"http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r":"http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "p":"http://schemas.openxmlformats.org/package/2006/relationships"}

def _col_index(ref: str) -> int:
    m = re.match(r"([A-Z]+)", ref or "A1")
    letters = m.group(1)
    out = 0
    for ch in letters:
        out = out*26 + (ord(ch)-64)
    return out-1

def read_sheet_rows(path: str, sheet_name: str):
    with ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall("m:si", NS):
                pieces = [t.text or "" for t in si.findall(".//m:t", NS)]
                shared.append("".join(pieces))
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        relmap = {r.attrib["Id"]: r.attrib["Target"] for r in rels.findall("p:Relationship", NS)}
        target = None
        for s in wb.findall("m:sheets/m:sheet", NS):
            if s.attrib.get("name") == sheet_name:
                rid = s.attrib.get("{%s}id" % NS["r"])
                target = relmap[rid]
                break
        if not target:
            raise KeyError(f"Worksheet not found: {sheet_name}")
        sheet_path = target.lstrip("/") if target.lstrip("/").startswith("xl/") else "xl/" + target.lstrip("/")
        root = ET.fromstring(z.read(sheet_path))
        rows=[]
        for r in root.findall(".//m:sheetData/m:row", NS):
            row=[]
            for c in r.findall("m:c", NS):
                idx = _col_index(c.attrib.get("r"))
                while len(row) <= idx:
                    row.append(None)
                typ = c.attrib.get("t")
                v = c.find("m:v", NS)
                if typ == "inlineStr":
                    t = c.find("m:is/m:t", NS)
                    val = t.text if t is not None else ""
                elif v is None:
                    val = None
                elif typ == "s":
                    val = shared[int(v.text)]
                elif typ == "b":
                    val = v.text == "1"
                else:
                    txt = v.text
                    try:
                        val = int(txt)
                    except:
                        try: val = float(txt)
                        except: val = txt
                row[idx]=val
            rows.append(row)
        return rows

def read_sheet_dicts(path: str, sheet_name: str):
    rows = read_sheet_rows(path, sheet_name)
    if not rows:
        return []
    headers = [str(x or "").strip() for x in rows[0]]
    out=[]
    for row in rows[1:]:
        row = row + [None]*(len(headers)-len(row))
        out.append({headers[i]: row[i] for i in range(len(headers))})
    return out
