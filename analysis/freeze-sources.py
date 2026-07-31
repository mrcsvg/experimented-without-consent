#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Congela os documentos auditados: captura, hash e Wayback.

O protocolo (§3, passo 2) exige arquivar cada documento na data de acesso —
"sem isso a auditoria não é reproduzível". Este é o executor desse passo.

    # 1. NUNCA pule: confirma de onde você está saindo
    python3 freeze-sources.py preflight

    # 2. inventário dos documentos citados como evidência
    python3 freeze-sources.py inventory --coded ../<repo-paper>/audit/coded-data.json \\
                                        --out frozen/inventory.json

    # 3. captura (recusa vantagem fora da UE, a menos que forçada)
    python3 freeze-sources.py capture --inventory frozen/inventory.json --out-dir frozen

    # 4. depois: o documento mudou desde o congelamento?
    python3 freeze-sources.py verify --out-dir frozen

POR QUE TEM QUE RODAR NA SUA MÁQUINA. Cinco serviços servem a tabela de base
legal só para tráfego da UE. A captura precisa sair da MESMA vantagem que a
codificação, o que significa: sua máquina, com a VPN da UE ligada. Um fetch
feito de qualquer outro lugar recaptura a visão errada em silêncio — daí o
`preflight` ser obrigatório e o `capture` recusar vantagem não-UE por padrão.

E POR QUE O WAYBACK NÃO BASTA SOZINHO. O Save Page Now captura da
infraestrutura do Internet Archive (EUA), não da sua VPN. Para os serviços
geo-restritos ele congela a visão não-UE — útil como prova pública de que a
URL existia e do que ela dizia ao mundo, inútil como registro do que o
codificador leu. Por isso as duas trilhas: texto+hash local (autoritativo,
fica no repo privado) e Wayback (verificável por terceiros, entra no pacote
público). O hash é o que liga uma coisa à outra sem redistribuir o documento.

Sem dependências externas: só a biblioteca padrão.
"""
import argparse, hashlib, html, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
# EEA + UK/CH: as vantagens que enxergam as tabelas de base legal por finalidade.
EU_ISO = {"AT","BE","BG","HR","CY","CZ","DK","EE","FI","FR","DE","GR","HU","IE","IT",
          "LV","LT","LU","MT","NL","PL","PT","RO","SK","SI","ES","SE","IS","LI","NO",
          "GB","CH"}
SPN = "https://web.archive.org/save/"
AVAIL = "http://archive.org/wayback/available"


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fetch(url, timeout=45, headers=None):
    """GET simples. Devolve (status, bytes, headers, final_url) e não levanta em 4xx/5xx."""
    req = urllib.request.Request(url, headers={"user-agent": UA,
                                               "accept-language": "en-GB,en;q=0.9",
                                               **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), dict(r.headers), r.url
    except urllib.error.HTTPError as e:
        return e.code, e.read() if e.fp else b"", dict(e.headers or {}), url
    except Exception as e:                       # DNS, TLS, timeout, reset
        return None, str(e).encode(), {}, url


# ---------------------------------------------------------------- vantagem

def vantage():
    """De onde estamos saindo. Nunca guarda o IP — só país e um hash curto."""
    for url, ckey in (("https://ipapi.co/json/", "country_code"),
                      ("http://ip-api.com/json/", "countryCode"),
                      ("https://ifconfig.co/json", "country_iso")):
        st, body, _, _ = fetch(url, timeout=12)
        if st != 200:
            continue
        try:
            j = json.loads(body.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            continue
        cc = (j.get(ckey) or "").upper()
        ip = j.get("ip") or j.get("query") or ""
        if cc:
            return {"country": cc, "in_eu_vantage": cc in EU_ISO,
                    "ip_sha256_8": hashlib.sha256(ip.encode()).hexdigest()[:8] if ip else None,
                    "checked_at": now_iso(), "via": urllib.parse.urlsplit(url).netloc}
    return {"country": None, "in_eu_vantage": False, "ip_sha256_8": None,
            "checked_at": now_iso(), "via": None}


# ------------------------------------------------------------ extração

TAG_BLOCK = re.compile(r"</?(p|div|br|li|tr|h[1-6]|section|article|header|footer|ul|ol|table)\b[^>]*>", re.I)
TAG_DROP = re.compile(r"<(script|style|noscript|svg|template)\b[^>]*>.*?</\1>", re.I | re.S)
TAG_ANY = re.compile(r"<[^>]+>")
COMMENT = re.compile(r"<!--.*?-->", re.S)


def charset_of(headers, body):
    m = re.search(r"charset=([\w\-]+)", headers.get("Content-Type", ""), re.I)
    if m:
        return m.group(1)
    m = re.search(rb'charset=["\']?([\w\-]+)', body[:4096], re.I)
    return m.group(1).decode("ascii", "replace") if m else "utf-8"


def extract_text(body, headers):
    """HTML -> texto. Determinístico: mesmo input, mesmo hash, sempre.

    É contra ESTE texto que a busca por palavra-chave do protocolo roda e é
    dele que saem as citações verbatim, então é ele que precisa ser hasheado
    — não o HTML cru, que muda por CSS, nonce e id de build sem que uma
    palavra do documento mude."""
    try:
        s = body.decode(charset_of(headers, body), "replace")
    except (LookupError, UnicodeDecodeError):
        s = body.decode("utf-8", "replace")
    s = COMMENT.sub(" ", s)
    s = TAG_DROP.sub(" ", s)
    s = TAG_BLOCK.sub("\n", s)
    s = TAG_ANY.sub(" ", s)
    s = html.unescape(s)
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in s.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def sha(b):
    return hashlib.sha256(b if isinstance(b, bytes) else b.encode("utf-8")).hexdigest()


def slug(s, n=60):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")[:n] or "doc"


# ------------------------------------------------------------ inventário

URL_RE = re.compile(r'https?://[^\s"\'<>,;)\]}]+')


def cmd_inventory(args):
    """Extrai as URLs de evidência da 1ª passada, com o contexto que as rotula."""
    recs = json.load(open(args.coded, encoding="utf-8"))
    items, seen = [], set()
    for r in recs:
        svc = r.get("service", "?")
        blob = r.get("docs_urls") or ""
        for m in URL_RE.finditer(blob):
            url = m.group(0).rstrip(".,;:")
            if (svc, url) in seen:
                continue
            seen.add((svc, url))
            # o texto que antecede a URL carrega o rótulo BINDING/NON-BINDING
            # e o nome do documento; guardado cru, para conferência humana.
            ctx = re.sub(r"\s+", " ", blob[max(0, m.start() - 160):m.start()]).strip()
            up = ctx.upper()
            role = ("non-binding" if "NON-BINDING" in up or "NON BINDING" in up
                    else "binding" if "BINDING" in up else "unknown")
            items.append({"service": svc, "url": url, "role_hint": role,
                          "context": ctx[-140:],
                          "pass1_access_date": r.get("access_date"),
                          "pass1_vantage": (r.get("eu_vantage") or "")[:120]})
    out = {"generated_at": now_iso(), "source": os.path.basename(args.coded),
           "documents": items}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n",
                              encoding="utf-8")
    by_role = {}
    for i in items:
        by_role[i["role_hint"]] = by_role.get(i["role_hint"], 0) + 1
    print(f"{len(items)} documentos, {len({i['service'] for i in items})} serviços -> {args.out}")
    print("  por rótulo:", ", ".join(f"{k}={v}" for k, v in sorted(by_role.items())))
    return 0


# ------------------------------------------------------------ Wayback

def wayback_save(url, pause):
    """Empurra para o Save Page Now e devolve a URL do snapshot (ou None).

    Anônimo o SPN é limitado e lento; 429 e 5xx são normais sob carga e não
    são falha de captura — a trilha local já está salva quando chegamos aqui."""
    st, _, hdrs, final = fetch(SPN + url, timeout=90)
    time.sleep(pause)
    if st in (429, 503, 502, 504):
        return None, f"SPN {st} (limite/indisponível)"
    cl = hdrs.get("Content-Location") or ""
    if cl.startswith("/web/"):
        return "https://web.archive.org" + cl, None
    if final and "/web/" in final:
        return final, None
    # SPN não devolveu o snapshot: pergunta ao índice qual é o mais recente.
    st, body, _, _ = fetch(f"{AVAIL}?url={urllib.parse.quote(url, safe='')}", timeout=30)
    if st == 200:
        try:
            snap = json.loads(body).get("archived_snapshots", {}).get("closest", {})
            if snap.get("available") and snap.get("url"):
                return snap["url"], None
        except json.JSONDecodeError:
            pass
    return None, f"sem snapshot (SPN {st})"


# ------------------------------------------------------------ captura

def cmd_capture(args):
    van = vantage()
    print(f"vantagem: {van['country'] or '?'} "
          f"({'UE/EEA — ok' if van['in_eu_vantage'] else 'FORA da UE'})")
    if not van["in_eu_vantage"] and not args.allow_any_vantage:
        print("\nRECUSANDO capturar de vantagem não-UE.", file=sys.stderr)
        print("Cinco serviços restringem a tabela de base legal ao tráfego da UE;", file=sys.stderr)
        print("capturar daqui congelaria a visão errada, em silêncio.", file=sys.stderr)
        print("Ligue a VPN da UE, ou passe --allow-any-vantage se for deliberado.", file=sys.stderr)
        return 2

    inv = json.load(open(args.inventory, encoding="utf-8"))["documents"]
    if args.service:
        inv = [d for d in inv if d["service"].lower().startswith(args.service.lower())]
    if args.limit:
        inv = inv[:args.limit]

    out = Path(args.out_dir)
    (out / "text").mkdir(parents=True, exist_ok=True)
    if args.keep_raw:
        (out / "raw").mkdir(parents=True, exist_ok=True)

    mpath = out / "manifest.json"
    man = json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else {
        "captured_at": None, "vantage": None, "documents": []}
    done = {d["url"] for d in man["documents"] if not d.get("error")}

    man["vantage"], man["captured_at"] = van, now_iso()
    ok = fail = skip = 0

    for i, doc in enumerate(inv, 1):
        url, svc = doc["url"], doc["service"]
        if url in done and not args.force:
            skip += 1
            continue
        print(f"[{i}/{len(inv)}] {svc[:24]:24} {url[:70]}")
        st, body, hdrs, final = fetch(url, timeout=args.timeout)
        entry = {"service": svc, "url": url, "final_url": final, "role_hint": doc["role_hint"],
                 "http_status": st, "captured_at": now_iso(),
                 "vantage_country": van["country"], "bytes": len(body),
                 "content_type": hdrs.get("Content-Type"), "error": None,
                 "sha256_raw": None, "sha256_text": None, "text_chars": 0,
                 "text_path": None, "wayback_url": None, "wayback_note": None}

        if st != 200 or not body:
            entry["error"] = f"HTTP {st}" if st else body.decode("utf-8", "replace")[:160]
            print(f"      ! {entry['error']}")
            fail += 1
        else:
            text = extract_text(body, hdrs)
            rel = f"text/{slug(svc)}/{i:03d}-{slug(urllib.parse.urlsplit(url).path or 'root', 40)}.txt"
            (out / rel).parent.mkdir(parents=True, exist_ok=True)
            (out / rel).write_text(text, encoding="utf-8")
            entry.update(sha256_raw=sha(body), sha256_text=sha(text),
                         text_chars=len(text), text_path=rel)
            if args.keep_raw:
                praw = out / rel.replace("text/", "raw/").replace(".txt", ".html")
                praw.parent.mkdir(parents=True, exist_ok=True)
                praw.write_bytes(body)
            print(f"      ok {len(text):>7} chars  sha {entry['sha256_text'][:12]}")
            ok += 1

        if not args.no_wayback:
            wb, note = wayback_save(url, args.wayback_pause)
            entry["wayback_url"], entry["wayback_note"] = wb, note
            print(f"      wb {wb or note}")

        man["documents"] = [d for d in man["documents"] if d["url"] != url] + [entry]
        mpath.write_text(json.dumps(man, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print(f"\ncapturados {ok} · falhas {fail} · já congelados {skip}")
    print(f"manifesto: {mpath}")
    return 0


# ------------------------------------------------------------ verificação

def cmd_verify(args):
    """Refetch e compara o hash do texto: o documento mudou desde o congelamento?"""
    out = Path(args.out_dir)
    man = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    docs = [d for d in man["documents"] if d.get("sha256_text")]
    if args.limit:
        docs = docs[:args.limit]
    van = vantage()
    print(f"vantagem agora: {van['country']} · congelado sob: {man.get('vantage',{}).get('country')}")
    if van["country"] != man.get("vantage", {}).get("country"):
        print("AVISO: vantagem diferente da do congelamento; diferença pode ser geo, não deriva.")
    same = moved = err = 0
    for d in docs:
        st, body, hdrs, _ = fetch(d["url"], timeout=args.timeout)
        if st != 200 or not body:
            print(f"  ?  {d['service'][:20]:20} HTTP {st} {d['url'][:60]}")
            err += 1
            continue
        h = sha(extract_text(body, hdrs))
        if h == d["sha256_text"]:
            same += 1
        else:
            moved += 1
            print(f"  MUDOU {d['service'][:20]:20} {d['url'][:64]}")
            print(f"        congelado {d['sha256_text'][:12]} em {d['captured_at'][:10]}"
                  f" -> agora {h[:12]}")
    print(f"\nidênticos {same} · mudaram {moved} · inacessíveis {err}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("preflight", help="de onde estou saindo?")

    p = sub.add_parser("inventory", help="monta a lista de documentos a congelar")
    p.add_argument("--coded", required=True, help="coded-data.json da 1ª passada")
    p.add_argument("--out", required=True)

    p = sub.add_parser("capture", help="captura, hasheia e arquiva")
    p.add_argument("--inventory", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--service", help="só os serviços com este prefixo")
    p.add_argument("--limit", type=int)
    p.add_argument("--timeout", type=int, default=45)
    p.add_argument("--keep-raw", action="store_true", help="guarda também o HTML cru")
    p.add_argument("--no-wayback", action="store_true")
    p.add_argument("--wayback-pause", type=float, default=8.0, help="s entre chamadas ao SPN")
    p.add_argument("--force", action="store_true", help="recaptura o que já está congelado")
    p.add_argument("--allow-any-vantage", action="store_true")

    p = sub.add_parser("verify", help="o documento mudou desde o congelamento?")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--limit", type=int)
    p.add_argument("--timeout", type=int, default=45)

    a = ap.parse_args()
    if a.cmd == "preflight":
        v = vantage()
        print(json.dumps(v, ensure_ascii=False, indent=1))
        print("\nvantagem UE: " + ("SIM, pode capturar" if v["in_eu_vantage"]
                                   else "NÃO — ligue a VPN antes de capturar"))
        return 0 if v["in_eu_vantage"] else 1
    return {"inventory": cmd_inventory, "capture": cmd_capture, "verify": cmd_verify}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
