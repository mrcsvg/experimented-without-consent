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
import argparse, difflib, gzip, hashlib, html, json, os, re, sys, time, zipfile, zlib
import urllib.error, urllib.parse, urllib.request
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
# Pacote completo, servido junto do corpus para quem prefere ler sem conexão.
ZIP_NAME = "corpus-congelado.zip"


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# Um UA de navegador com o resto dos headers faltando é assinatura de bot, e
# vários destes serviços recusam por isso e não por bloqueio de verdade: sem
# `accept` a Meta devolve 400 em todos os domínios e o Stripchat devolve 406,
# que é literalmente "não sei atender esse Accept". Medido: 4 de 5 URLs que
# falhavam passam a 200 só com o conjunto completo abaixo.
BROWSER = {
    "user-agent": UA,
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
              "image/avif,image/webp,*/*;q=0.8",
    "accept-language": "en-GB,en;q=0.9",
    "accept-encoding": "gzip, deflate",
    "upgrade-insecure-requests": "1",
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
}


GZIP_MAGIC = b"\x1f\x8b"


def _decode(body, enc):
    """Pedimos gzip, então temos de desempacotar — hashear bytes comprimidos
    daria um hash instável e um texto ilegível.

    NÃO confia no Content-Encoding. Quatro documentos da 1ª rodada chegaram
    gzipados sem o header dizer: o caminho de HTTPError perde headers, e CDN
    às vezes simplesmente omite. Sem o header, os bytes comprimidos seguiam
    direto para extract_text, que os decodificava com errors="replace" — o
    resultado era ~44% de U+FFFD gravado como se fosse a política. Pinterest
    perdeu as três vinculantes exatamente assim, e nada no pipeline reclamou.

    Sniffar o magic é barato e cobre header ausente, header errado e gzip
    duplo de CDN mal configurado."""
    unpacked = False
    for _ in range(2):                          # duas camadas bastam na prática
        if body[:2] != GZIP_MAGIC:
            break
        try:
            body, unpacked = gzip.decompress(body), True
        except (OSError, zlib.error):
            break                               # o magic mentiu: devolve como veio
    if unpacked or enc != "deflate":
        return body
    # deflate não tem magic confiável — só aqui ainda dependemos do header
    for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS):   # zlib e raw deflate
        try:
            return zlib.decompress(body, wbits)
        except zlib.error:
            continue
    return body


def fetch(url, timeout=45, headers=None, retries=2):
    """GET. Devolve (status, bytes, headers, final_url) e não levanta em 4xx/5xx.

    Repete em timeout e 5xx — parte das falhas do Zalando é lentidão, não recusa."""
    req = urllib.request.Request(url, headers={**BROWSER, **(headers or {})})
    last = (None, b"", {}, url)
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return (r.status, _decode(r.read(), (r.headers.get("Content-Encoding") or "").lower()),
                        dict(r.headers), r.url)
        except urllib.error.HTTPError as e:
            hh = dict(e.headers or {})
            body = _decode(e.read(), (hh.get("Content-Encoding") or "").lower()) if e.fp else b""
            if e.code < 500 and e.code != 429:
                return e.code, body, hh, url          # recusa definitiva: não insiste
            last = (e.code, body, hh, url)
        except Exception as e:                        # DNS, TLS, timeout, reset
            last = (None, str(e).encode(), {}, url)
        if attempt < retries:
            time.sleep(2 * (attempt + 1))
    return last


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


PDF_MAGIC = b"%PDF"


class NotText(RuntimeError):
    """Corpo que não é texto e não dá para extrair aqui.

    Existe para que a captura FALHE em vez de gravar lixo: um corpo binário
    passado pelo extrator de HTML vira mojibake com contagem de caracteres
    alta, o que engana a porta de texto-vazio e entra no corpus como se fosse
    a política."""


def garbage_ratio(text):
    """Fração de U+FFFD. Texto real fica em ~0; decodificação errada, em 0,3-0,5."""
    return text.count("�") / max(len(text), 1)


def extract_pdf(body):
    """PDF -> texto. Precisa de pypdf; sem ele, falha em vez de gravar lixo.

    Dois documentos VINCULANTES do Zalando são PDF servido de CDN
    (mosaic02.ztat.net, Content-Type: application/pdf). Passados pelo extrator
    de HTML, viravam 34-43% de U+FFFD — e ainda assim somavam 542.865
    caracteres, folgadamente acima de --min-text. Só a contagem de lixo pega
    esse caso; o tamanho não pega."""
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise NotText("é PDF e o pypdf não está instalado (`pip install pypdf`)") from e
    import io
    paginas = [(p.extract_text() or "") for p in PdfReader(io.BytesIO(body)).pages]
    linhas = [re.sub(r"[ \t\xa0]+", " ", ln).strip() for ln in "\n".join(paginas).split("\n")]
    return "\n".join(ln for ln in linhas if ln)


def extract_text(body, headers):
    """Documento -> texto. Determinístico: mesmo input, mesmo hash, sempre.

    É contra ESTE texto que a busca por palavra-chave do protocolo roda e é
    dele que saem as citações verbatim, então é ele que precisa ser hasheado
    — não o HTML cru, que muda por CSS, nonce e id de build sem que uma
    palavra do documento mude.

    Levanta NotText quando o corpo não é algo de que se extraia texto aqui."""
    if body[:4] == PDF_MAGIC:
        return extract_pdf(body)
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


def membros(man, inv):
    """{serviço: [entrada, ...]} — quem USA cada documento, não quem disparou a captura.

    O manifesto guarda uma entrada por URL, e está certo assim: capturar a mesma
    página duas vezes, em horas diferentes, poria duas versões do mesmo
    documento no corpus. Mas a unidade de análise é o serviço, e a passada 1
    listou a mesma Privacy Policy do Google para os cinco serviços do Google. O
    `service` de uma entrada só diz qual serviço estava na vez quando a URL foi
    buscada. Agrupar por ele tirou do Google Search cinco documentos que a
    passada 1 leu — a Privacy Policy em duas localizações, os Terms, a política
    de cookies e a página "rigorous testing", a dos 700 mil experimentos — e os
    deixou só com o Shopping e o Play. O instrumento em HTML escapou porque
    mapeia por URL; o índice do kit, a varredura do §3 e o corpus em Markdown,
    que agrupavam por `service`, não.

    A pertença vem do inventário (os pares serviço–URL da passada 1); o conteúdo,
    do manifesto. Entrada adotada à mão cuja URL não está no inventário fica com
    o serviço que o `adopt` gravou, que é a única atribuição existente para ela.
    O `role_hint` vem do par, porque é o contexto daquele serviço que rotulou.
    """
    por_url = {d["url"]: d for d in man["documents"]}
    grupos, usadas = {}, set()
    for par in inv["documents"]:
        entrada = por_url.get(par["url"])
        if entrada is None:
            continue
        usadas.add(par["url"])
        grupos.setdefault(par["service"], []).append(
            {**entrada, "service": par["service"],
             "role_hint": par.get("role_hint") or entrada.get("role_hint")})
    for d in man["documents"]:
        if d["url"] not in usadas:
            grupos.setdefault(d["service"], []).append(d)
    return grupos


def carregar_membros(out):
    """Lê manifesto e inventário de `out` e devolve (manifesto, membros).

    Sem o inventário não há como saber quem usa cada documento, e cair de volta
    no `service` do manifesto é exatamente o erro que `membros` corrige — por
    isso a falta dele é erro, não fallback."""
    out = Path(out)
    man = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    caminho = out / "inventory.json"
    if not caminho.exists():
        sys.exit(f"{caminho} não existe. Sem o inventário, a pertença dos documentos "
                 "compartilhados cairia para o serviço que disparou a captura.")
    inv = json.loads(caminho.read_text(encoding="utf-8"))
    return man, membros(man, inv)


# ------------------------------------------------------------ Wayback

def wayback_save(url, pause):
    """Empurra para o Save Page Now e devolve a URL do snapshot (ou None).

    Anônimo o SPN limita agressivamente: em teste, 1 de 2 capturas levou 429.
    Para as ~167 URLs da auditoria isso é inviável — crie chaves em
    archive.org/account/s3.php e exporte antes de rodar:

        export IA_ACCESS_KEY=...  IA_SECRET_KEY=...

    429 e 5xx não são falha de captura: a trilha local (a autoritativa) já
    está salva quando chegamos aqui, e a próxima execução só tenta de novo as
    URLs que ficaram sem `wayback_url`."""
    hdr = {}
    ak, sk = os.environ.get("IA_ACCESS_KEY"), os.environ.get("IA_SECRET_KEY")
    if ak and sk:
        hdr["authorization"] = f"LOW {ak}:{sk}"
    st, _, hdrs, final = fetch(SPN + url, timeout=90, headers=hdr)
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
    prev = {d["url"]: d for d in man["documents"]}

    man["vantage"], man["captured_at"] = van, now_iso()
    ok = fail = skip = wb_ok = 0

    for i, doc in enumerate(inv, 1):
        url, svc = doc["url"], doc["service"]
        was = prev.get(url)
        # As duas trilhas são independentes de propósito: a recomendação é rodar
        # --no-wayback primeiro (rápido, é o que destrava o coder 2) e voltar
        # depois para o Wayback, que é lento. Se o skip fosse do documento
        # inteiro, a segunda passada não arquivaria nada.
        # Uma captura fina gravada por uma versão anterior tem sha e não tem erro,
        # então precisa entrar aqui explicitamente ou ficaria congelada vazia.
        need_fetch = (args.force or not was or was.get("error")
                      or not was.get("sha256_text")
                      or (was.get("capture_method") != "manual"
                          and was.get("text_chars", 0) < args.min_text))
        need_wb = not args.no_wayback and (args.force or not (was or {}).get("wayback_url"))
        if not need_fetch and not need_wb:
            skip += 1
            continue
        print(f"[{i}/{len(inv)}] {svc[:24]:24} {url[:70]}")
        entry = dict(was) if was else {
            "service": svc, "url": url, "role_hint": doc["role_hint"], "error": None,
            "sha256_raw": None, "sha256_text": None, "text_chars": 0,
            "text_path": None, "wayback_url": None, "wayback_note": None}

        if need_fetch:
            st, body, hdrs, final = fetch(url, timeout=args.timeout)
            entry.update(final_url=final, http_status=st, captured_at=now_iso(),
                         vantage_country=van["country"], bytes=len(body),
                         content_type=hdrs.get("Content-Type"), error=None)
            # Extrai UMA vez: além do desperdício, extract_text agora pode
            # levantar, e chamá-la três vezes espalharia o tratamento.
            try:
                text = extract_text(body, hdrs) if (st == 200 and body) else ""
                nao_texto = None
            except NotText as e:
                text, nao_texto = "", str(e)

            if st != 200 or not body:
                entry["error"] = f"HTTP {st}" if st else body.decode("utf-8", "replace")[:160]
                print(f"      ! {entry['error']}")
                fail += 1
            elif nao_texto:
                entry.update(final_url=final, http_status=st, bytes=len(body), error=None)
                entry["error"] = f"corpo não textual: {nao_texto}"
                print(f"      ! {entry['error']}")
                fail += 1
            elif len(text) < args.min_text:
                # 200 com corpo grande e texto quase nulo = shell renderizado por
                # JS, que o urllib não executa. É a falha PERIGOSA: sem esta porta
                # ela conta como sucesso e congela documento vazio em silêncio.
                # Medido na 1ª rodada: 17 de 128 "sucessos" — Temu inteira a 0
                # caractere, as três vinculantes da Shein a ~400 de 500KB de HTML.
                entry.update(final_url=final, http_status=st, bytes=len(body), error=None)
                entry["error"] = (f"texto vazio ({len(text)} ch de {len(body)}b) — provável "
                                  f"render por JS; use `adopt` com o HTML salvo do navegador")
                print(f"      ! {entry['error']}")
                fail += 1
            elif garbage_ratio(text) > 0.02:
                # A porta acima mede TAMANHO e por isso não pega decodificação
                # errada: mojibake é longo. Foi assim que 6 dos 143 documentos
                # entraram no corpus como sucesso — 34% a 45% de U+FFFD, com
                # Pinterest e Zalando perdendo o conjunto vinculante inteiro.
                # Texto real fica em ~0%; 2% é folgado e não dá falso positivo.
                pct = 100 * garbage_ratio(text)
                entry.update(final_url=final, http_status=st, bytes=len(body), error=None)
                entry["error"] = (f"texto ilegível ({pct:.0f}% U+FFFD em {len(text)} ch) — "
                                  f"decodificação errada, não recongele por cima")
                print(f"      ! {entry['error']}")
                fail += 1
            else:
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
        else:
            print(f"      · texto já congelado ({entry['sha256_text'][:12]})")

        if need_wb:
            wb, note = wayback_save(url, args.wayback_pause)
            entry["wayback_url"], entry["wayback_note"] = wb, note
            wb_ok += 1 if wb else 0
            print(f"      wb {wb or note}")

        man["documents"] = [d for d in man["documents"] if d["url"] != url] + [entry]
        mpath.write_text(json.dumps(man, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print(f"\ncapturados {ok} · falhas {fail} · nada a fazer {skip}"
          + (f" · arquivados no Wayback {wb_ok}" if not args.no_wayback else ""))
    print(f"manifesto: {mpath}")
    return 0


# ------------------------------------------------------------ verificação

def cmd_status(args):
    """O que está de fato congelado, por serviço — e o que só parece estar."""
    man = json.loads((Path(args.out_dir) / "manifest.json").read_text(encoding="utf-8"))
    docs = man["documents"]
    by = {}
    for d in docs:
        s = by.setdefault(d["service"], {"ok": 0, "bad": 0, "manual": 0, "wb": 0, "urls": []})
        # Mesma porta do `capture`, aplicada ao que já está gravado: um manifesto
        # escrito antes dela marca as capturas finas como boas, e sem repetir o
        # teste aqui o status herdaria a mesma mentira.
        thin = (d.get("capture_method") != "manual"
                and (d.get("text_chars") or 0) < args.min_text)
        good = not d.get("error") and d.get("sha256_text") and not thin
        s["ok" if good else "bad"] += 1
        s["manual"] += 1 if d.get("capture_method") == "manual" else 0
        s["wb"] += 1 if d.get("wayback_url") else 0
        if not good:
            why = d.get("error") or (f"texto vazio ({d.get('text_chars', 0)} ch)" if thin else "?")
            s["urls"].append((d["url"], why[:44]))
    # Um manifesto montado só por `adopt` nunca passou pelo `capture` e não tem
    # nem carimbo nem vantagem — é um estado válido, não um erro.
    quando = (man.get("captured_at") or "")[:16] or "só adoções manuais"
    print(f"congelado em {quando} · vantagem "
          f"{(man.get('vantage') or {}).get('country') or '?'}\n")
    print(f"{'serviço':38} {'ok':>4} {'falta':>6} {'manual':>7} {'wayback':>8}")
    print("-" * 68)
    tot_ok = tot_bad = 0
    for svc in sorted(by, key=lambda k: (-by[k]["bad"], k)):
        s = by[svc]
        tot_ok += s["ok"]; tot_bad += s["bad"]
        flag = "  <-- SEM NENHUM" if s["ok"] == 0 else ""
        print(f"{svc[:38]:38} {s['ok']:>4} {s['bad']:>6} {s['manual']:>7} {s['wb']:>8}{flag}")
    print("-" * 68)
    print(f"{'TOTAL':38} {tot_ok:>4} {tot_bad:>6}")
    if args.detail:
        print("\n=== pendentes ===")
        for svc in sorted(by):
            for u, e in by[svc]["urls"]:
                print(f"  {svc[:20]:20} {e:46} {u[:70]}")
    return 0


FREEZE_MARK = re.compile(rb"<!--\s*FREEZE-SOURCE\s+(\S+?)\s*-->")


def embedded_url(body):
    """A URL que salvar-dom.js grava na 1ª linha do arquivo.

    Sem isso o vínculo arquivo->documento depende do nome do arquivo, que o
    navegador decide e o humano digita — dois lugares para errar em silêncio.
    Adotar sob a URL errada gravaria o congelamento no documento errado."""
    m = FREEZE_MARK.search(body[:2048])
    return m.group(1).decode("utf-8", "replace") if m else None


def cmd_package(args):
    """Monta o kit do 2º codificador: só o corpus, nunca as codificações.

    Precisa ser um artefato separado. O corpus vive no repo privado do paper,
    que guarda as codificações da 1ª passada — dar acesso a ele ao codificador
    quebraria a cegueira que o 2º passe existe para estabelecer. Daqui sai um
    zip com o texto, um índice por serviço e as instruções, e nada mais."""
    out, dest = Path(args.out_dir), Path(args.dest)
    man, grupos = carregar_membros(out)

    def bom(d):
        return (d.get("text_path") and not d.get("error")
                and (d.get("capture_method") == "manual" or (d.get("text_chars") or 0) >= args.min_text))

    good = [d for d in man["documents"] if bom(d)]
    by = {s: [d for d in v if bom(d)] for s, v in grupos.items()}
    by = {s: v for s, v in by.items() if v}

    idx = {"built_at": now_iso(), "frozen_at": man.get("captured_at"),
           "vantage": (man.get("vantage") or {}).get("country"),
           "services": {s: [{"url": d["url"], "file": d["text_path"],
                             "chars": d["text_chars"], "sha256": d["sha256_text"],
                             "captured_at": d["captured_at"],
                             "manual": d.get("capture_method") == "manual"}
                            for d in sorted(v, key=lambda x: x["url"])]
                        for s, v in sorted(by.items())}}

    readme = f"""# Corpus congelado — 2º passe de codificação

Congelado em {(man.get('captured_at') or '?')[:10]}, de vantagem {idx['vantage']} (UE).
{len(good)} documentos, {len(by)} serviços.

## Por que ler daqui e não do site

Os documentos das plataformas mudam sem aviso. Se os dois codificadores lerem
versões diferentes da mesma página, a discordância entre eles deixa de ser
discordância de codificação e vira deriva do documento, e depois não há como
separar as duas. Ler deste corpus garante que os dois passes leram o mesmo
texto.

Há um ganho prático junto: o protocolo exige registrar, por documento, a
contagem de cada termo da busca por palavra-chave. Em texto plano o Ctrl-F /
Cmd-F conta certo. Na página ao vivo ele erra, porque parte do conteúdo só
existe depois do JavaScript, ou aparece conforme você rola.

## Como usar

Abra **`index.html`** (duplo clique). Ele lista os documentos por serviço, com a
URL de origem ao lado, e clica direto no arquivo. `index.json` traz o mesmo em
formato de dados, se preferir.

Cada arquivo começa com um cabeçalho dizendo de onde veio:

```
==============================================================================
FONTE      https://help.x.com/en/rules-and-policies/x-cookies
CAPTURADO  2026-07-31T16:12:03+00:00  ·  vantagem IT
MÉTODO     captura automatizada (HTTP)
SHA-256    e294269a13b0…
           (do texto abaixo da linha, sem este cabeçalho)
------------------------------------------------------------------------------
```

## Como o texto foi extraído (e o que isso implica)

O que está aqui é o **texto** do documento, não a página. A extração remove
scripts, estilos e as marcações de HTML, desfaz as entidades (`&amp;` volta a
ser `&`) e normaliza o espaço em branco. O que sobra é a prosa na ordem em que
aparecia.

Consequências que importam para a codificação:

- **Não há formatação.** Tabelas viram linhas soltas; a tabela de bases legais
  por finalidade, por exemplo, aparece como sequência de células. O conteúdo
  está lá, a grade não.
- **Não há imagens nem elementos interativos.** Se um documento comunicasse algo
  só por imagem, isso não estaria aqui — não encontramos nenhum caso, mas se
  desconfiar, registre.
- **Menus, rodapés e banners de cookie entram no texto**, porque fazem parte da
  página. Ignore-os; não são o documento.
- Documentos marcados **manual** foram salvos pelo navegador, com a página já
  montada, porque o site monta o conteúdo por JavaScript ou recusa acesso
  automatizado. São equivalentes em conteúdo; a diferença de procedência fica
  registrada porque ela existe, não porque compromete algo.

Se algum documento parecer incompleto, truncado, ou não corresponder à URL do
cabeçalho, **registre no campo "Problemas de acesso" do instrumento e não
codifique o campo afetado** — como o protocolo já manda para link morto. É
preferível uma célula vazia e explicada a uma célula preenchida sobre texto
duvidoso.

## Conferir que um arquivo não foi alterado

O SHA-256 do cabeçalho cobre o texto abaixo dele — o cabeçalho tem 7 linhas
mais uma em branco, então o corpo começa na linha 9:

```bash
tail -n +9 arquivo.txt | shasum -a 256
```

Deve bater com o SHA-256 do cabeçalho. Não batendo, avise: significa que o
arquivo foi editado depois do congelamento.

## O que NÃO está aqui

Nenhuma codificação, de nenhum passe. O 2º passe é cego por desenho: você
codifica a partir do documento e do codebook, sem ver o que foi codificado
antes.
"""
    # Índice navegável: file:// abrindo file:// funciona, então dá para clicar do
    # índice para o documento sem servidor nenhum. Procurar arquivo em 26 pastas
    # com nome derivado de URL seria a pior parte do trabalho dele.
    esc = lambda s: (str(s).replace("&", "&amp;").replace("<", "&lt;")
                     .replace(">", "&gt;").replace('"', "&quot;"))
    linhas = []
    for s, v in idx["services"].items():
        linhas.append(f'<h2>{esc(s)} <small>{len(v)} doc.</small></h2><table>')
        for d in v:
            marca = ' <b class="m">manual</b>' if d["manual"] else ""
            linhas.append(
                f'<tr><td><a href="{esc(d["file"])}">{esc(d["file"].split("/")[-1])}</a>{marca}</td>'
                f'<td class="n">{d["chars"]:,}</td>'
                f'<td class="u"><a href="{esc(d["url"])}" target="_blank" rel="noopener">'
                f'{esc(d["url"])}</a></td></tr>'.replace(",", "."))
        linhas.append("</table>")
    html = f"""<!doctype html><html lang="pt-BR"><meta charset="utf-8">
<title>Corpus congelado — 2º passe</title><style>
body{{font:15px/1.5 system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#1a1a1a}}
h1{{font-size:22px;margin-bottom:.2rem}} h2{{font-size:16px;margin:1.6rem 0 .3rem;border-bottom:1px solid #ddd;padding-bottom:.2rem}}
h2 small{{font-weight:400;color:#777;font-size:12px}}
table{{border-collapse:collapse;width:100%}} td{{padding:3px 8px 3px 0;vertical-align:top;font-size:13.5px}}
td.n{{color:#777;text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}}
td.u a{{color:#777;font-size:12px;word-break:break-all}}
b.m{{background:#fff3cd;color:#7a5c00;font-size:10.5px;padding:1px 5px;border-radius:3px;font-weight:600}}
.aviso{{background:#f6f8fa;border-left:3px solid #2da44e;padding:.7rem 1rem;border-radius:0 5px 5px 0;font-size:13.5px}}
.baixar{{display:flex;align-items:center;gap:.8rem;flex-wrap:wrap;background:#f6f8fa;
  border:1px solid #d0d7de;border-radius:6px;padding:.7rem 1rem;margin:1rem 0;font-size:13.5px}}
.baixar a{{background:#1f883d;color:#fff;text-decoration:none;font-weight:600;
  padding:6px 14px;border-radius:6px;white-space:nowrap}}
.baixar a:hover{{background:#1a7f37}}
.baixar span{{color:#57606a}}
a{{color:#0969da}}</style>
<h1>Corpus congelado — 2º passe de codificação</h1>
<p class="aviso"><b>Leia o arquivo, não a página.</b> Congelado em
{esc((man.get('captured_at') or '?')[:10])}, de vantagem {esc(idx['vantage'])}.
{len(good)} documentos, {len(by)} serviços. A URL ao lado está aí como procedência,
para a citação — abri-la hoje pode trazer outra versão do documento.
Cada arquivo abre com um cabeçalho dizendo de onde veio, quando e como.</p>
<div class="baixar" id="baixar" hidden>
  <a href="{ZIP_NAME}" download>Baixar o corpus inteiro</a>
  <span>{ZIP_NAME} · {len(good)} documentos · ZIP_MB MB — para ler sem conexão, ou
  buscar um termo nos {len(good)} documentos de uma vez, com grep ou com a busca
  do seu editor.</span>
</div>
<script>
/* Some quando a página já está sendo lida do arquivo baixado: ali o link não
   resolve, e oferecer download de quem já baixou é ruído. */
if (location.protocol !== "file:") document.getElementById("baixar").hidden = false;
</script>
{''.join(linhas)}
<p style="color:#777;font-size:12px;margin-top:2rem">
<b class="m">manual</b> = página que monta por JavaScript ou recusa cliente
automatizado; salva pelo navegador na mesma vantagem. Ver LEIA-ME.md.</p>
</html>"""

    dest.mkdir(parents=True, exist_ok=True)
    (dest / "index.json").write_text(json.dumps(idx, ensure_ascii=False, indent=1) + "\n",
                                     encoding="utf-8")
    (dest / "index.html").write_text(html, encoding="utf-8")
    (dest / "LEIA-ME.md").write_text(readme, encoding="utf-8")
    # O kit é exatamente estes arquivos. A lista existe porque `dest` é o repo
    # publicado, e não uma pasta de trabalho: varrer o diretório para montar o
    # zip levaria junto `.git/`, `.vercel/` e `.env.local` — que o .gitignore
    # esconde do commit e um rglob() cego reintroduziria pela porta do zip.
    kit = [dest / "index.json", dest / "index.html", dest / "LEIA-ME.md"]
    n = 0
    for d in good:
        src, dst = out / d["text_path"], dest / d["text_path"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        # Cabeçalho de procedência: sem ele o avaliador abre um .txt anônimo e,
        # para saber de que documento se trata, tem de cruzar o index.json à mão
        # — exatamente na hora em que está em dúvida. O hash continua sendo o do
        # corpo, e o cabeçalho diz isso, para não parecer que cobre a si mesmo.
        modo = ("captura manual pelo navegador (a página monta por JavaScript "
                "ou recusa cliente automatizado)" if d.get("capture_method") == "manual"
                else "captura automatizada (HTTP)")
        cab = (f"{'='*78}\n"
               f"FONTE      {d['url']}\n"
               f"CAPTURADO  {d['captured_at']}  ·  vantagem "
               f"{d.get('vantage_country') or '?'}\n"
               f"MÉTODO     {modo}\n"
               f"SHA-256    {d['sha256_text']}\n"
               f"           (do texto abaixo da linha, sem este cabeçalho)\n"
               f"{'-'*78}\n\n")
        dst.write_text(cab + src.read_text(encoding="utf-8"), encoding="utf-8")
        kit.append(dst)
        n += 1
    # Documento que saiu do manifesto — recaptura renumerou, ou a entrada passou
    # a ter erro — continuaria em disco e no zip, ausente do índice. O leitor
    # veria um .txt que a auditoria não reconhece, e um `find` no corpus contaria
    # o mesmo documento duas vezes. O manifesto manda; o que ele não lista, sai.
    conhecidos = {p.resolve() for p in kit}
    for p in sorted((dest / "text").rglob("*.txt")):
        if p.resolve() not in conhecidos:
            print(f"  removido (fora do manifesto): {p.relative_to(dest)}")
            p.unlink()
    # Pasta que o Finder/iCloud criou resolvendo nome duplicado ("text 2", vazia,
    # modo 700), ou que ficou vazia pela remoção acima: some depois de montar.
    for p in sorted(dest.rglob("*"), key=lambda q: -len(q.parts)):
        if p.is_dir() and not any(p.iterdir()):
            p.rmdir()
    # Montado por último e sem se incluir. Existe para quem quer o corpus na
    # máquina — ler offline, ou buscar um termo nos 143 documentos de uma vez,
    # que é justamente o que o protocolo pede e a leitura documento a documento
    # não facilita.
    zpath = dest / ZIP_NAME

    def montar_zip():
        zpath.unlink(missing_ok=True)
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for p in kit:
                z.write(p, p.relative_to(dest))
        return zpath.stat().st_size / 1048576

    # O índice anuncia o tamanho do zip, e o zip contém o índice: monta uma vez
    # para medir, escreve o número, monta de novo. A segunda passada difere da
    # primeira por alguns bytes — invisível na casa decimal que exibimos.
    mb = montar_zip()
    ipath = dest / "index.html"
    ipath.write_text(ipath.read_text(encoding="utf-8").replace("ZIP_MB", f"{mb:.1f}"),
                     encoding="utf-8")
    mb = montar_zip()

    print(f"kit em {dest}: {n} documentos, {len(by)} serviços")
    print(f"  index.html (abrir com duplo clique) · index.json · LEIA-ME.md · text/")
    print(f"  {ZIP_NAME} — {mb:.1f} MB, o corpus inteiro")
    missing = sorted({d["service"] for d in man["documents"]} - set(by))
    if missing:
        print(f"\n  ATENÇÃO — serviços sem nenhum documento no kit: {', '.join(missing)}")
    thin = [s for s, v in by.items() if len(v) < 2]
    if thin:
        print(f"  serviços com só 1 documento: {', '.join(thin)}")
    return 0


def cmd_adopt(args):
    """Adota no congelamento um arquivo salvo à mão pelo navegador.

    Existe porque alguns serviços bloqueiam cliente automatizado de verdade —
    o help center do X devolve 403 a qualquer combinação de headers. Um proxy
    de renderização resolveria o acesso e estragaria a vantagem: ele busca da
    infra dele, não da sua VPN, e justamente essas páginas variam por região.
    Salvar pelo navegador, na VPN, é o único caminho que preserva as duas
    coisas.

    A entrada fica marcada `capture_method: "manual"` para que a diferença de
    procedência apareça no manifesto em vez de se perder."""
    out = Path(args.out_dir)
    mpath = out / "manifest.json"
    man = json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else {
        "captured_at": None, "vantage": None, "documents": []}
    body = Path(args.file).read_bytes()
    url = args.url or embedded_url(body)
    if not url:
        sys.exit(f"{args.file} não traz o marcador FREEZE-SOURCE e --url não foi passado.\n"
                 "Salve com analysis/salvar-dom.js, ou informe --url à mão.")
    if body[:8] == b"bplist00":
        sys.exit("isso é um .webarchive (formato binário da Apple), que este script não lê.\n"
                 "Salve o DOM renderizado como HTML — ver --help do adopt.")
    text = extract_text(body, {"Content-Type": "text/html; charset=utf-8"})
    # Mesma porta do `capture`, e aqui ela pega o erro mais provável do fluxo
    # manual: salvar o código-fonte em vez do DOM renderizado devolve o mesmo
    # shell vazio que motivou o adopt, e sem esta checagem entraria como bom.
    if len(text) < args.min_text:
        sys.exit(f"o arquivo rende só {len(text)} caracteres de texto ({len(body)}b de HTML).\n"
                 f"Se a página é renderizada por JS, você salvou o código-fonte e não o DOM.\n"
                 f"Ver `adopt --help`. Para forçar assim mesmo: --min-text 0")
    rel = f"text/{slug(args.service)}/manual-{slug(urllib.parse.urlsplit(url).path or 'root', 40)}.txt"
    (out / rel).parent.mkdir(parents=True, exist_ok=True)
    (out / rel).write_text(text, encoding="utf-8")
    entry = {"service": args.service, "url": url, "final_url": url,
             "role_hint": args.role, "http_status": None, "captured_at": now_iso(),
             "capture_method": "manual", "manual_note": args.note,
             "vantage_country": args.vantage, "bytes": len(body),
             "content_type": "text/html", "error": None,
             "sha256_raw": sha(body), "sha256_text": sha(text), "text_chars": len(text),
             "text_path": rel, "wayback_url": None, "wayback_note": None}
    man["documents"] = [d for d in man["documents"] if d["url"] != url] + [entry]
    mpath.write_text(json.dumps(man, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"adotado  {args.service}  {len(text)} chars  sha {entry['sha256_text'][:12]}")
    print(f"  -> {rel}")
    return 0


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
    same = moved = err = cosm = 0
    report = []
    for d in docs:
        st, body, hdrs, _ = fetch(d["url"], timeout=args.timeout)
        if st != 200 or not body:
            print(f"  ?  {d['service'][:20]:20} HTTP {st} {d['url'][:60]}")
            err += 1
            report.append({**{k: d[k] for k in ("service", "url")},
                           "verdict": "inacessível", "http_status": st})
            continue
        new = extract_text(body, hdrs)
        h = sha(new)
        if h == d["sha256_text"]:
            same += 1
            report.append({**{k: d[k] for k in ("service", "url")}, "verdict": "idêntico"})
            continue
        old = (out / d["text_path"]).read_text(encoding="utf-8") if d.get("text_path") else ""
        # Quantas linhas mudaram importa mais que "mudou": bump de data de
        # vigência e reescrita do parágrafo de bases legais pesam diferente na
        # adjudicação, e o hash sozinho não distingue os dois.
        dl = list(difflib.unified_diff(old.split("\n"), new.split("\n"),
                                       "congelado", "agora", lineterm="", n=args.context))
        adds = sum(1 for l in dl if l.startswith("+") and not l.startswith("+++"))
        dels = sum(1 for l in dl if l.startswith("-") and not l.startswith("---"))
        # Hash igual a "mudou" é brutal demais: as páginas do Booking carregam
        # uma linha com os IDs dos testes A/B DELAS, que se reordena a cada
        # request. Sem este corte, todo documento sai alterado em toda checagem
        # e a medição de deriva vira ruído puro. O que importa para adjudicar é
        # magnitude — 1 linha de mobília não é reescrita de cláusula.
        cosmetic = max(adds, dels) <= args.noise_lines
        moved += 0 if cosmetic else 1
        cosm += 1 if cosmetic else 0
        print(f"  {'ruído ' if cosmetic else 'MUDOU '} {d['service'][:20]:20} {d['url'][:62]}")
        print(f"         {dels} linhas saíram, {adds} entraram"
              + (" — abaixo do corte, provável mobília de página" if cosmetic else ""))
        report.append({**{k: d[k] for k in ("service", "url")},
                       "verdict": "ruído" if cosmetic else "mudou",
                       "sha256_frozen": d["sha256_text"], "sha256_now": h,
                       "frozen_at": d["captured_at"], "lines_removed": dels,
                       "lines_added": adds})
        if args.diff and not (cosmetic and args.only_substantive):
            for l in dl[:args.max_diff_lines]:
                print("        " + l[:150])
            if len(dl) > args.max_diff_lines:
                print(f"        … mais {len(dl)-args.max_diff_lines} linhas de diff")
    print(f"\nidênticos {same} · ruído {cosm} (≤{args.noise_lines} linhas) "
          f"· MUDARAM {moved} · inacessíveis {err}")
    if moved:
        print("os que mudaram de verdade precisam entrar na adjudicação: a discordância "
              "\nentre passes nesses documentos pode ser deriva, não codificação.")
    if args.report:
        Path(args.report).write_text(json.dumps(
            {"checked_at": now_iso(), "vantage": van,
             "frozen_manifest_at": man.get("captured_at"),
             "noise_threshold_lines": args.noise_lines,
             "totals": {"identical": same, "cosmetic": cosm,
                        "changed": moved, "unreachable": err},
             "documents": report}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"relatório: {args.report}")
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
    p.add_argument("--min-text", type=int, default=1000,
                   help="abaixo disto a captura é tratada como falha: um documento "
                        "jurídico não tem 400 caracteres, é shell de JS (0 desliga)")
    p.add_argument("--keep-raw", action="store_true", help="guarda também o HTML cru")
    p.add_argument("--no-wayback", action="store_true")
    p.add_argument("--wayback-pause", type=float, default=15.0,
                   help="s entre chamadas ao SPN (anônimo precisa de folga; com "
                        "IA_ACCESS_KEY/IA_SECRET_KEY dá para baixar bastante)")
    p.add_argument("--force", action="store_true", help="recaptura o que já está congelado")
    p.add_argument("--allow-any-vantage", action="store_true")

    p = sub.add_parser("package", help="monta o kit do codificador (corpus, sem codificações)")
    p.add_argument("--out-dir", required=True, help="o diretório congelado")
    p.add_argument("--dest", required=True, help="onde montar o kit")
    p.add_argument("--min-text", type=int, default=1000)

    p = sub.add_parser("status", help="o que está de fato congelado, por serviço")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--detail", action="store_true", help="lista as URLs pendentes")
    p.add_argument("--min-text", type=int, default=1000)

    p = sub.add_parser(
        "adopt", help="adota um arquivo salvo à mão (para os que bloqueiam)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
COMO SALVAR — precisa ser o DOM RENDERIZADO, não o código-fonte.

  Temu, Shein e afins montam a página por JS. "Salvar como / somente HTML" e
  "Exibir código-fonte" devolvem o shell vazio, que é justamente o que o
  `capture` já pegou. Com a VPN da UE ligada e a página aberta:

    1. DevTools (⌥⌘I) > Console
    2. copy(document.documentElement.outerHTML)
    3. no terminal:  pbpaste > ~/Downloads/temu-tos.html

  Alternativa no Chrome: ⌘S > "Página da Web, completa" (serializa o DOM
  atual, ao contrário de "somente HTML"). No Safari, "Fonte da página" NÃO
  serve e ".webarchive" é binário e não é lido aqui.

  Confira antes de adotar:  grep -c . arquivo.html
""")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--min-text", type=int, default=1000,
                   help="rejeita arquivo com menos texto que isto (0 desliga)")
    p.add_argument("--url", help="opcional: por padrão lê o marcador FREEZE-SOURCE do arquivo")
    p.add_argument("--file", required=True, help="o .html salvo pelo navegador")
    p.add_argument("--service", required=True)
    p.add_argument("--role", default="unknown", choices=["binding", "non-binding", "unknown"])
    p.add_argument("--vantage", default=None, help="país de onde você salvou (ex.: IT)")
    p.add_argument("--note", default="salvo pelo navegador na VPN da UE")

    p = sub.add_parser("verify", help="o documento mudou desde o congelamento?")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--limit", type=int)
    p.add_argument("--timeout", type=int, default=45)
    p.add_argument("--diff", action="store_true", help="mostra o que mudou, não só que mudou")
    p.add_argument("--context", type=int, default=1, help="linhas de contexto no diff")
    p.add_argument("--max-diff-lines", type=int, default=40)
    p.add_argument("--noise-lines", type=int, default=2,
                   help="até quantas linhas alteradas contam como mobília de página "
                        "e não como deriva do documento")
    p.add_argument("--only-substantive", action="store_true",
                   help="com --diff, omite o diff do que ficou abaixo do corte")
    p.add_argument("--report", help="grava o veredito por documento em JSON")

    a = ap.parse_args()
    if a.cmd == "preflight":
        v = vantage()
        print(json.dumps(v, ensure_ascii=False, indent=1))
        print("\nvantagem UE: " + ("SIM, pode capturar" if v["in_eu_vantage"]
                                   else "NÃO — ligue a VPN antes de capturar"))
        return 0 if v["in_eu_vantage"] else 1
    return {"inventory": cmd_inventory, "capture": cmd_capture, "status": cmd_status,
            "package": cmd_package, "adopt": cmd_adopt, "verify": cmd_verify}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
