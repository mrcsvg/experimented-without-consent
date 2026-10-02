#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""O painel com o ipywidgets de verdade, sem navegador.

    python3 analysis/teste-widgets-reais.py      # precisa de ipywidgets e IPython

POR QUE ALÉM DO SELF-TEST. O `revisao --self-test` usa um ipywidgets de mentira
que aceita qualquer coisa. O de verdade valida cada atributo na construção:
valor de Dropdown fora das opções, None num campo de texto, tupla onde se espera
lista. Esses erros estourariam no Colab, na frente do codificador, e passariam
pelo stub. Aqui os 26 painéis são montados com os widgets reais, e um serviço é
codificado inteiro clicando nos botões: dez variáveis, voltar, notas, reabrir.

Sem o ipywidgets instalado, o script diz isso e sai com 0 (é o `pre-entrega` que
decide se a ausência conta). Para rodar numa máquina sem ele:

    python3 -m venv /tmp/w && /tmp/w/bin/pip install ipywidgets ipython
    /tmp/w/bin/python analysis/teste-widgets-reais.py
"""
import json
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "analysis"))
CORPUS = RAIZ.parent / "experimented-without-consent-corpus" / "md"


def main() -> int:
    try:
        import IPython.display as ipd
        import ipywidgets as W
    except ImportError:
        print("pulou: ipywidgets não está instalado neste python (ver o cabeçalho)")
        return 0
    tela = []
    ipd.display = lambda *a, **k: tela.extend(a)
    import codebook as C
    import coding_flow as F
    import revisao as R
    R.configurar(corpus=str(CORPUS), modelo="x")
    falhas = []

    def checar(desc, cond, detalhe=""):
        print(("  ok    " if cond else "  FALHA ") + desc + (f" [{detalhe}]" if not cond and detalhe else ""))
        if not cond:
            falhas.append(desc)

    def arvore(x):
        yield x
        for c in getattr(x, "children", ()) or ():
            yield from arvore(c)

    def widgets():
        return [w for x in tela if isinstance(x, W.Widget) for w in arvore(x)]

    def clicar(prefixo):
        [b for b in widgets() if isinstance(b, W.Button)
         and b.description.startswith(prefixo)][-1].click()

    def campos(painel):
        caixa = [x for x in widgets() if isinstance(x, W.VBox) and x.children and all(
            isinstance(h, W.HBox) and len(h.children) == 2 and isinstance(h.children[0], W.Label)
            for h in x.children)][-1]
        por_rotulo = {c.rotulo: c.chave for c in painel.fluxo.atual().campos}
        return {por_rotulo[h.children[0].value]: h.children[1] for h in caixa.children}

    def responder(cs):
        for chave, w in cs.items():
            c = next(c for v in C.VARIAVEIS for c in v.campos if c.chave == chave)
            if c.tipo == "select":
                w.value = [o for o in c.opcoes if o][0]
            elif c.tipo == "checks":
                w.value = tuple(o for o in c.opcoes if o)[:1]
            elif chave != "keyword_log":
                w.value = f"teste {chave}"

    print(f"ipywidgets {W.__version__}")
    erros = []
    for s in C.SERVICOS:
        try:
            tela.clear()
            R.Painel(s, estado=F.Estado(offline=True, cache=Path(tempfile.mkdtemp()) / "e.json"),
                     assistir=False).mostrar()
        except Exception as e:
            erros.append(f"{s}: {type(e).__name__}: {e}"[:150])
    checar("os 26 painéis montam com widgets reais", not erros, "; ".join(erros[:2]))

    cache = Path(tempfile.mkdtemp()) / "e.json"
    tela.clear()
    p = R.Painel("Zalando", estado=F.Estado(offline=True, cache=cache), assistir=False)
    p.mostrar()
    responder(campos(p)); clicar("salvar V1")
    checar("salvar avança para a V2", p.fluxo.atual().vid == "V2")
    clicar("voltar"); checar("voltar retorna à V1", p.fluxo.atual().vid == "V1")
    for _ in range(10):
        vid = p.fluxo.atual().vid
        responder(campos(p)); clicar(f"salvar {vid}")
    gravado = json.loads(cache.read_text())["records"]["Zalando"]
    checar("as dez variáveis fecham", F.Fluxo("Zalando", F.Estado(offline=True, cache=cache))
           .progresso() == (10, 10))
    checar("multi-seleção grava lista", isinstance(gravado.get("v2_framing"), list))
    notas = [w for w in widgets() if isinstance(w, W.Textarea)
             and "Dúvidas de regra" in (w.placeholder or "")][-1]
    notas.value = "nota"; clicar("salvar notas")
    checar("notas gravam", json.loads(cache.read_text())["records"]["Zalando"].get("notes") == "nota")
    try:
        tela.clear()
        R.Painel("Zalando", estado=F.Estado(offline=True, cache=cache), assistir=False).mostrar()
        checar("reabrir um serviço respondido devolve os valores aos widgets", True)
    except Exception as e:
        checar("reabrir um serviço respondido devolve os valores aos widgets", False, str(e)[:150])
    print(f"\n{'FALHOU: ' + str(len(falhas)) if falhas else 'tudo ok'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
