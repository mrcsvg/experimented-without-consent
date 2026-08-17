import gzip, importlib.util, sys, zlib
from pathlib import Path

INST = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("fs", INST / "analysis" / "freeze-sources.py")
fs = importlib.util.module_from_spec(spec); sys.modules["fs"] = fs; spec.loader.exec_module(fs)

def _raw_deflate(b):
    """Raw deflate de verdade: comprime e dá flush no MESMO objeto."""
    co = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    return co.compress(b) + co.flush()


PAYLOAD = b"<!DOCTYPE html><p>we run A/B tests</p>"
gz = gzip.compress(PAYLOAD)

casos = [
    ("gzip SEM header  (o bug do Pinterest)", gz,                    "",         PAYLOAD),
    ("gzip com header  (caminho normal)",     gz,                    "gzip",     PAYLOAD),
    ("gzip com header ERRADO",                gz,                    "deflate",  PAYLOAD),
    ("gzip duplo, sem header (CDN)",          gzip.compress(gz),     "",         PAYLOAD),
    ("texto puro, sem header",                PAYLOAD,               "",         PAYLOAD),
    ("texto puro, header mente gzip",         PAYLOAD,               "gzip",     PAYLOAD),
    ("deflate (zlib) com header",             zlib.compress(PAYLOAD), "deflate", PAYLOAD),
    ("raw deflate com header",                _raw_deflate(PAYLOAD), "deflate",  PAYLOAD),
    ("magic gzip mentiroso (lixo)",           b"\x1f\x8bNAO_E_GZIP", "",         b"\x1f\x8bNAO_E_GZIP"),
    ("PDF, sem header",                       b"%PDF-1.4 corpo",     "",         b"%PDF-1.4 corpo"),
]

falhas = 0
print("%-42s %s" % ("caso", "resultado"))
print("-" * 62)
for nome, entrada, enc, esperado in casos:
    got = fs._decode(entrada, enc)
    ok = got == esperado
    falhas += not ok
    print("%-42s %s" % (nome, "ok" if ok else "FALHA got=%r" % got[:28]))
print()
print("=== _decode: %d/%d ===" % (len(casos) - falhas, len(casos)))
sys.exit(1 if falhas else 0)
