#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Higiene dos notebooks: nenhum output entra no git.

    python3 analysis/nb-clean.py --install        # configura ESTE clone (uma vez)
    python3 analysis/nb-clean.py --check-staged   # o que o hook pre-commit chama
    python3 analysis/nb-clean.py --write f.ipynb  # limpa no lugar, na mão

POR QUE OUTPUT DE NOTEBOOK NÃO PODE SER COMMITADO AQUI. Não é questão de diff
limpo. O `02-llm-recall-sweep` devolve passagens que o modelo achou e que o
codificador humano não achou — é exatamente o que não pode chegar ao 2º
avaliador durante a passagem de concordância. E o `01-keyword-sweep` manda ele
clonar este repo. Um output salvo no 02 viaja no clone que o próprio protocolo
mandou fazer: a contaminação entra pela porta da frente.

DUAS CAMADAS, PORQUE UMA FALHA EM SILÊNCIO. O filtro `clean` zera os outputs
antes de virarem índice, e você commita sem pensar nisso. Mas configuração de
filtro não viaja no clone: numa máquina sem ela, o `.gitattributes` é ignorado
sem avisar e o output passa. Por isso o hook, que olha o blob já staged — o que
de fato seria commitado — e aborta. O filtro é a conveniência; o hook é a
garantia.

Nenhuma das duas viaja sozinha: `--install` tem que rodar uma vez por clone.

DE QUEBRA, CANONIZA. O `source` volta como lista de linhas terminadas em \\n,
que é o que o nbformat exige. Os dois notebooks já foram gravados uma vez sem
esses terminadores — no Colab cada célula colapsava numa linha só e quebrava na
primeira execução. Passando pelo git, não tem como regredir.

Sem dependências externas: só a biblioteca padrão.
"""
import json
import subprocess
import sys
from pathlib import Path

# Metadado que o Colab injeta a cada execução e que muda sem o notebook mudar.
LIXO_CELULA = ("executionInfo", "outputId", "colab", "collapsed", "scrolled")
LIXO_NOTEBOOK = ("widgets",)


def _linhas(source):
    """Devolve o source como lista de linhas terminadas em \\n."""
    if isinstance(source, str):
        texto = source
    elif len(source) > 1 and not any(l.endswith("\n") for l in source[:-1]):
        # Lista sem terminador nenhum: são linhas, não fragmentos. Juntar com ""
        # aqui é o bug que colapsava a célula inteira numa linha só.
        texto = "\n".join(source)
    else:
        texto = "".join(source)
    return texto.splitlines(keepends=True)


def limpar(nb):
    """Zera outputs e canoniza. Devolve (notebook, tinha_output)."""
    tinha = False
    for c in nb.get("cells", []):
        if c.get("outputs"):
            tinha = True
        if c.get("cell_type") == "code":
            c["outputs"] = []
            c["execution_count"] = None
        if "source" in c:
            c["source"] = _linhas(c["source"])
        for k in LIXO_CELULA:
            c.get("metadata", {}).pop(k, None)
    for k in LIXO_NOTEBOOK:
        nb.get("metadata", {}).pop(k, None)
    return nb, tinha


def serializar(nb):
    """Sempre a mesma forma para o mesmo conteúdo — diff só mostra o que mudou."""
    return json.dumps(nb, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def cmd_filter():
    """Filtro `clean` do git: notebook na stdin, notebook limpo na stdout."""
    bruto = sys.stdin.read()
    try:
        nb, _ = limpar(json.loads(bruto))
    except (json.JSONDecodeError, AttributeError, TypeError):
        # Não é um .ipynb válido. O filtro não é lugar de decidir isso: devolve
        # como veio e deixa o erro aparecer onde dá para entender.
        sys.stdout.write(bruto)
        return 0
    sys.stdout.write(serializar(nb))
    return 0


def cmd_check_staged():
    """Recusa o commit se algum .ipynb staged carrega output."""
    r = subprocess.run(["git", "diff", "--cached", "--name-only",
                        "--diff-filter=ACM", "--", "*.ipynb"],
                       capture_output=True, text=True)
    arquivos = [l for l in r.stdout.split("\n") if l.strip()]
    sujos = []
    for f in arquivos:
        blob = subprocess.run(["git", "show", f":{f}"], capture_output=True, text=True)
        if blob.returncode:
            continue
        try:
            nb = json.loads(blob.stdout)
        except json.JSONDecodeError:
            continue
        n = sum(1 for c in nb.get("cells", []) if c.get("outputs"))
        if n:
            sujos.append((f, n))
    if not sujos:
        return 0
    print("\ncommit abortado — notebook com output no índice:\n", file=sys.stderr)
    for f, n in sujos:
        print(f"  {f}  ({n} células com output)", file=sys.stderr)
    print("\nOutput de notebook não entra neste repo: o 02 devolve passagens que\n"
          "o codificador humano não achou, e o repo é clonado pelo 2º avaliador.\n"
          "\nO filtro que evita isso não está configurado neste clone. Rode:\n"
          "\n    python3 analysis/nb-clean.py --install\n"
          "\ne refaça o `git add`. Para limpar na mão:\n"
          "\n    python3 analysis/nb-clean.py --write " + " ".join(f for f, _ in sujos)
          + "\n", file=sys.stderr)
    return 1


def cmd_write(caminhos):
    for c in caminhos:
        p = Path(c)
        nb, tinha = limpar(json.loads(p.read_text(encoding="utf-8")))
        antes = p.read_text(encoding="utf-8")
        depois = serializar(nb)
        p.write_text(depois, encoding="utf-8")
        estado = "output removido" if tinha else ("canonizado" if antes != depois else "já limpo")
        print(f"  {p}  ({estado})")
    return 0


def cmd_install():
    """Configura filtro e hooks NESTE clone. Idempotente."""
    raiz = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True, check=True).stdout.strip()
    raiz = Path(raiz)
    for chave, valor in (("filter.nbclean.clean", "python3 analysis/nb-clean.py --filter"),
                         ("filter.nbclean.smudge", "cat"),
                         ("core.hooksPath", ".githooks")):
        subprocess.run(["git", "config", chave, valor], cwd=raiz, check=True)
        print(f"  git config {chave} = {valor}")
    hook = raiz / ".githooks" / "pre-commit"
    if hook.exists():
        hook.chmod(0o755)
        print(f"  {hook.relative_to(raiz)} executável")
    else:
        print(f"  AVISO: {hook} não existe — a 2ª camada está faltando", file=sys.stderr)
    print("\nConfigurado. O filtro só afeta o que vai para o índice; o arquivo em\n"
          "disco continua com os outputs da sua execução.")
    return 0


def main(argv):
    if not argv:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    modo, resto = argv[0], argv[1:]
    if modo == "--filter":
        return cmd_filter()
    if modo == "--check-staged":
        return cmd_check_staged()
    if modo == "--install":
        return cmd_install()
    if modo == "--write":
        if not resto:
            print("--write precisa de pelo menos um arquivo", file=sys.stderr)
            return 2
        return cmd_write(resto)
    print(f"modo desconhecido: {modo}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
