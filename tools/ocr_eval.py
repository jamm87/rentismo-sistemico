"""Mide recall de importes y de palabras de descripción de Tesseract frente a la referencia xerraires.
Uso: python -I tools/ocr_eval.py PDF COD_PARLAMENTARIO DIR_SALIDA   (requiere tesseract-ocr + tesseract-ocr-spa y poppler-utils)
Ejecutar desde la raíz del repo con PYTHONPATH=src."""
import re, sqlite3, subprocess, sys, time
from pathlib import Path
from decimal import Decimal
from rentismo.normalize import parse_importe_es, strip_accents
pdf, cod, outdir = Path(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3])
outdir.mkdir(parents=True, exist_ok=True)
t0 = time.time(); texts = {}
for psm in (4, 6):
    txt = ""
    for pg in (2, 3, 4):   # páginas de bienes/deudas (la 1 son datos personales y rentas, la 5 observaciones/firma)
        base = outdir / f"p{pg}"
        subprocess.run(["pdftoppm", "-f", str(pg), "-l", str(pg), "-r", "300", "-gray", "-png", str(pdf), str(base)], check=True)
        img = next(outdir.glob(f"p{pg}-*.png"))
        txt += subprocess.run(["tesseract", str(img), "-", "-l", "spa", "--psm", str(psm)], capture_output=True, text=True).stdout + "\n"
    texts[psm] = txt
print(f"  tiempo OCR (6 pasadas de página): {time.time()-t0:.0f}s")
con = sqlite3.connect("db/rentismo.sqlite")
ref = con.execute("select seccion, descripcion, valor from ext_xerraires_bien where cod_parlamentario=? and ocurrencia=1", (cod,)).fetchall()
num_re = re.compile(r"\d[\d.,'’]*\d|\d")
def nums(t):
    out = set()
    for m in num_re.findall(t):
        v = parse_importe_es(m)
        if v is not None: out.add(v)
    return out
amounts = [Decimal(v) for _, _, v in ref if v]
words = lambda t: set(re.findall(r"[a-z]{4,}", strip_accents(t).lower()))
for name, txt in (("psm4", texts[4]), ("psm6", texts[6]), ("psm4+6", texts[4] + texts[6])):
    n = nums(txt)
    hit = sum(a in n for a in amounts)
    dw = [w for _, d, _ in ref if d for w in words(d)]
    tw = words(txt)
    print(f"  {name:7} importes {hit}/{len(amounts)} = {hit/max(1,len(amounts)):.0%} | palabras de descripción {sum(w in tw for w in dw)}/{len(dw)} = {sum(w in tw for w in dw)/max(1,len(dw)):.0%}")
