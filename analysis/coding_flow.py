#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fluxo linear de codificação: uma variável por vez, critério antes da resposta.

    import coding_flow as F
    e = F.Estado()                       # sincroniza com o instrumento
    f = F.Fluxo("Pinterest", e)
    p = f.atual()                        # V1: título, regra, critério, âncoras
    f.responder({"v1_code": "2", "v1_register": "binding",
                 "v1_evidence": "“...” — Privacy Policy §3"})
    f.avancar()                          # só passa se o portão deixar

    python3 analysis/coding_flow.py --self-test

POR QUE LINEAR. O que o instrumento em HTML não consegue impedir é a rolagem: as
nove variáveis ficam na mesma tela, e quem lê V9 antes de decidir V1 já viu para
onde o serviço aponta. Aqui uma variável só existe depois que a anterior fechou.
Não é ergonomia, é a mesma razão pela qual as âncoras do piloto são suprimidas —
o instrumento não põe a resposta no campo de visão durante a decisão.

O PORTÃO. Para avançar: toda pergunta respondida e o campo de evidência
preenchido. É mais estrito que o HTML, de propósito. O achado central do estudo
é uma coluna de "No", e "No" sem evidência é exatamente o zero não-auditável que
o paper existe para criticar. Onde a ausência for do tipo "o registro nunca
contempla o tema", isso *é* a evidência — escreva, que o portão abre. O que ele
recusa é o campo vazio.

O portão nunca opina sobre o valor. Ele só verifica que há resposta e há
justificativa; qual resposta, e se ela está certa, não é assunto dele.

PERSISTÊNCIA. O mesmo `/api/state` que o HTML usa — cada gravação vira commit no
branch `coder2-data`. O PUT substitui o objeto `records` inteiro, então grava-se
sempre GET → merge → PUT: enviar só o que este fluxo codificou apagaria o que
foi feito no HTML. O merge é por serviço, o mais recente vence (`_ts`), que é a
mesma regra do `Sync.init()` do instrumento.

Cópia local em disco a cada resposta, antes da rede. Se o endpoint estiver fora,
ou o runtime do Colab morrer, o que já foi codificado está no arquivo.

Sem dependências externas: só a biblioteca padrão.
"""
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import codebook as C  # noqa: E402

BASE = "https://experimented-without-consent.vercel.app"
CACHE = Path("coder2-local.json")
TIMEOUT = 20

# Campo `line` é opcional, exceto quando a resposta o torna exigível: dizer que
# existe programa opt-in sem dizer qual não é uma codificação verificável.
LINE_EXIGIDA = {"v6_which": ("v6_optin_beta", "Yes")}


class Estado:
    """Registros dos 26 serviços, em disco e (quando dá) no servidor."""

    def __init__(self, base=BASE, cache=CACHE, offline=False):
        self.base, self.cache, self.offline = base, Path(cache), offline
        self.records, self.online = {}, False
        self.carregar()

    # ------------------------------------------------------------------ rede
    def _get(self):
        req = urllib.request.Request(f"{self.base}/api/state", method="GET")
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8")).get("records") or {}

    def _put(self, records):
        corpo = json.dumps({"records": records}).encode("utf-8")
        req = urllib.request.Request(f"{self.base}/api/state", data=corpo, method="PUT",
                                     headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status == 200

    # ----------------------------------------------------------------- disco
    def _ler_cache(self):
        if not self.cache.exists():
            return {}
        try:
            return json.loads(self.cache.read_text(encoding="utf-8")).get("records") or {}
        except (json.JSONDecodeError, OSError):
            return {}

    def _gravar_cache(self):
        self.cache.write_text(json.dumps({"records": self.records}, ensure_ascii=False,
                                         indent=1) + "\n", encoding="utf-8")

    # --------------------------------------------------------------- público
    @staticmethod
    def _merge(a, b):
        """Une por serviço; em conflito, o registro com `_ts` maior vence."""
        out = dict(a)
        for svc, rec in b.items():
            atual = out.get(svc)
            if not atual or (rec.get("_ts") or 0) > (atual.get("_ts") or 0):
                out[svc] = rec
        return out

    def carregar(self):
        local = self._ler_cache()
        if self.offline:
            self.records, self.online = local, False
            return
        try:
            self.records = self._merge(local, self._get())
            self.online = True
        except (urllib.error.URLError, OSError, ValueError):
            self.records, self.online = local, False

    def registro(self, servico):
        return dict(self.records.get(servico) or {})

    def gravar(self, servico, rec, rede=True):
        """Disco primeiro, rede depois. Devolve True se chegou ao servidor.

        `rede=False` grava só em disco — é o que se usa a cada tecla digitada.
        Um PUT por caractere viraria um commit por caractere no `coder2-data`.
        A rede entra quando a variável fecha.
        """
        rec = dict(rec)
        rec["_ts"] = int(time.time() * 1000)
        self.records[servico] = rec
        self._gravar_cache()
        if self.offline or not rede:
            return False
        try:
            # Relê antes de escrever: outro dispositivo pode ter avançado.
            self.records = self._merge(self._get(), {servico: rec})
            self._gravar_cache()
            self.online = self._put(self.records)
            return self.online
        except (urllib.error.URLError, OSError, ValueError):
            self.online = False
            return False


# ------------------------------------------------------------------- o fluxo

@dataclass
class Passo:
    vid: str
    titulo: str
    regra: str
    criterio: str
    campos: list
    ancoras: list = field(default_factory=list)
    ancoras_suprimidas: list = field(default_factory=list)


def resolver_servico(nome, chaves):
    """Casa o nome curto da UI com a chave longa do dossiê. Exato, ou prefixo único.

    O instrumento chama de "Temu"; o manifesto, de "Temu (Whaleco Technology
    Limited; DSA VLOP)". Onze dos 26 diferem assim. A tentação é o `.get()` com
    default vazio, e é errada: log vazio é indistinguível de serviço que não
    acende nenhum termo — o codificador registraria um zero que é artefato de
    nome. Prefixo ambíguo também levanta: "Google Search" não pode casar com
    "Google Shopping" por descuido de substring.
    """
    if nome in chaves:
        return nome
    cand = sorted(k for k in chaves if k.startswith(nome))
    if len(cand) == 1:
        return cand[0]
    raise KeyError(f"{nome!r} resolveu para {cand or 'nada'} no dossiê — esperava exatamente 1")


class Fluxo:
    def __init__(self, servico, estado, dossie=None):
        if servico not in C.SERVICOS:
            raise KeyError(f"{servico!r} não está no frame — veja codebook.SERVICOS")
        self.servico, self.estado = servico, estado
        self.rec = estado.registro(servico)
        self.dossie = dossie or {}
        # Resolve na construção, não na hora de usar: se o nome não casa, o erro
        # tem que aparecer antes de o codificador começar a ler o serviço.
        self.chave_dossie = resolver_servico(servico, self.dossie) if self.dossie else None
        self.i = 0

    # ------------------------------------------------------------ navegação
    @property
    def passos(self):
        return C.VARIAVEIS

    def atual(self):
        v = self.passos[self.i]
        mostrar, ocultas = C.ancoras(v.crit_key, self.servico)
        return Passo(v.vid, v.titulo, v.regra, C.criterio(v.crit_key),
                     v.campos, mostrar, ocultas)

    def responder(self, respostas, rede=True):
        """Grava as respostas desta variável. Não valida o valor, só registra."""
        chaves = {c.chave for c in self.passos[self.i].campos}
        estranhas = set(respostas) - chaves
        if estranhas:
            raise KeyError(f"campos que não são desta variável: {sorted(estranhas)}")
        self.rec.update(respostas)
        return self.estado.gravar(self.servico, self.rec, rede=rede)

    def faltando(self, indice=None):
        """O que o portão ainda espera. Lista vazia = pode avançar."""
        v = self.passos[self.i if indice is None else indice]
        pend = []
        for c in v.campos:
            valor = self.rec.get(c.chave)
            vazio = not valor or (isinstance(valor, list) and not valor)
            if c.tipo in ("select", "checks") and vazio:
                pend.append((c.chave, "resposta"))
            elif c.tipo == "text" and vazio:
                # Exigir por TIPO, não pelo sufixo do nome: `keyword_log` é o
                # único campo de texto que não se chama *_evidence/*_note, e a
                # regra por sufixo o deixava passar vazio — logo o log que o
                # codebook marca como obrigatório e que torna cada "No" auditável.
                pend.append((c.chave, "log §3" if c.chave == "keyword_log" else "evidência"))
            elif c.chave in LINE_EXIGIDA and vazio:
                gatilho, valor_gatilho = LINE_EXIGIDA[c.chave]
                if self.rec.get(gatilho) == valor_gatilho:
                    pend.append((c.chave, f"exigido porque {gatilho} = {valor_gatilho}"))
        return pend

    def pode_avancar(self):
        return not self.faltando()

    def avancar(self):
        pend = self.faltando()
        if pend:
            raise PortaoFechado(self.passos[self.i].vid, pend)
        if self.i + 1 >= len(self.passos):
            return False
        self.i += 1
        return True

    def voltar(self):
        """Rever o que já foi respondido é permitido; pular adiante não."""
        if self.i == 0:
            return False
        self.i -= 1
        return True

    # --------------------------------------------------------------- dossiê
    def log_sugerido(self):
        """As contagens do §3 para este serviço, em texto — para o campo KW.

        Contagem crua, com o aviso onde o termo costuma dar falso positivo. A
        triagem é do codificador: o dossiê diz onde o termo aparece, não o que
        ele significa.
        """
        linhas = []
        for d in self.evidencia():
            conta = d.get("log_line") or " / ".join(f"{t}:{n}" for t, n in d["counts"].items())
            linhas.append(f"{Path(d['file']).name}: {conta}")
        return "\n".join(linhas)

    def evidencia(self):
        """Documentos do serviço com contagens e KWIC, para a triagem do §3.

        Devolve o que a máquina achou e onde. Nada aqui é veredito: `test` conta
        `testing` de QA junto com teste A/B, e separar os dois é leitura humana.
        """
        return self.dossie.get(self.chave_dossie) or []

    def progresso(self):
        feitas = sum(1 for n in range(len(self.passos)) if not self.faltando(n))
        return feitas, len(self.passos)


class PortaoFechado(RuntimeError):
    def __init__(self, vid, pendencias):
        self.vid, self.pendencias = vid, pendencias
        detalhe = " · ".join(f"{k} ({p})" for k, p in pendencias)
        super().__init__(f"{vid} ainda não fechou: {detalhe}")


# ---------------------------------------------------------------- self-test

def _self_test():
    import tempfile
    falhas = []

    def checar(desc, cond):
        print(f"  {'ok  ' if cond else 'FALHA'} {desc}")
        if not cond:
            falhas.append(desc)

    tmp = Path(tempfile.mkdtemp()) / "estado.json"
    e = Estado(cache=tmp, offline=True)
    f = Fluxo("Pinterest", e)

    print("Navegação e portão:")
    checar("começa em V1", f.atual().vid == "V1")
    checar("portão fechado com registro vazio", not f.pode_avancar())
    try:
        f.avancar()
        checar("avancar() levanta PortaoFechado", False)
    except PortaoFechado as ex:
        checar("avancar() levanta PortaoFechado", "V1" in str(ex))

    f.responder({"v1_code": "2", "v1_register": "binding"})
    checar("resposta sem evidência ainda barra",
           ("v1_evidence", "evidência") in f.faltando())
    f.responder({"v1_evidence": "“testing new features” — Privacy Policy"})
    checar("com evidência, o portão abre", f.pode_avancar())
    checar("avancar() vai para V2", f.avancar() and f.atual().vid == "V2")
    checar("voltar() volta para V1", f.voltar() and f.atual().vid == "V1")

    print("\nEscopo dos campos:")
    try:
        f.responder({"v9_where": ["help centre"]})
        checar("responder() recusa campo de outra variável", False)
    except KeyError:
        checar("responder() recusa campo de outra variável", True)

    print("\nRegra condicional (v6_which):")
    f6 = Fluxo("Pinterest", Estado(cache=tmp, offline=True))
    f6.i = [v.vid for v in f6.passos].index("V6")
    f6.responder({"v6_optin_beta": "No"})
    checar("V6=No não exige 'qual'", f6.pode_avancar())
    f6.responder({"v6_optin_beta": "Yes"})
    checar("V6=Yes exige 'qual'", not f6.pode_avancar())
    f6.responder({"v6_which": "Pinterest public beta"})
    checar("com 'qual' preenchido, abre", f6.pode_avancar())

    print("\nSupressão de âncora dentro do fluxo:")
    fg = Fluxo("Google Play", Estado(cache=tmp, offline=True))
    checar("âncora do Google some em Google Play",
           len(fg.atual().ancoras_suprimidas) == 1 and len(fg.atual().ancoras) == 2)
    fw = Fluxo("Wikipedia", Estado(cache=tmp, offline=True))
    checar("Wikipedia vê as três", not fw.atual().ancoras_suprimidas)

    print("\nPersistência (merge não pode apagar o que veio de fora):")
    alheio = {"Temu": {"v1_code": "0", "_ts": 10}}
    meu = {"Pinterest": {"v1_code": "3", "_ts": 20}}
    juntos = Estado._merge(alheio, meu)
    checar("merge preserva registro alheio", set(juntos) == {"Temu", "Pinterest"})
    velho = Estado._merge({"Temu": {"v1_code": "1", "_ts": 99}}, {"Temu": {"v1_code": "0", "_ts": 10}})
    checar("em conflito, o _ts maior vence", velho["Temu"]["v1_code"] == "1")

    e2 = Estado(cache=tmp, offline=True)
    checar("registro sobrevive à releitura do disco",
           e2.registro("Pinterest").get("v1_code") == "2")

    print("\nO log §3 é obrigatório (era o furo do portão):")
    fk = Fluxo("Pinterest", Estado(cache=tmp, offline=True))
    fk.i = [v.vid for v in fk.passos].index("KW")
    checar("KW vazio NÃO passa", not fk.pode_avancar())
    checar("o que falta é o log", fk.faltando() == [("keyword_log", "log §3")])
    fk.responder({"keyword_log": "001-en-privacy-policy.txt: experiment:0 / test:4"})
    checar("com o log preenchido, fecha", fk.pode_avancar())

    print("\nResolução do nome do dossiê:")
    chaves = ["Temu (Whaleco Technology Limited; DSA VLOP)", "X", "XNXX",
              "XVideos (WebGroup Czech Republic, a.s.; DSA VLOP)",
              "Google Search (Google Ireland Ltd.; DSA VLOSE)",
              "Google Shopping (provider Google Ireland Ltd.; DSA type)"]
    checar("prefixo único resolve",
           resolver_servico("Temu", chaves).startswith("Temu ("))
    checar("exato ganha de prefixo ('X' não vira 'XNXX')",
           resolver_servico("X", chaves) == "X")
    checar("'Google Search' não casa com 'Google Shopping'",
           resolver_servico("Google Search", chaves).startswith("Google Search"))
    try:
        resolver_servico("Inexistente", chaves)
        checar("nome sem correspondência levanta", False)
    except KeyError:
        checar("nome sem correspondência levanta", True)

    dossie_real = Path(__file__).resolve().parent / "keyword-hits.json"
    if dossie_real.exists():
        d = json.loads(dossie_real.read_text(encoding="utf-8"))["servicos"]
        com_log = 0
        for s in C.SERVICOS:
            fx = Fluxo(s, Estado(cache=tmp, offline=True), dossie=d)
            com_log += bool(fx.log_sugerido())
        checar(f"os 26 serviços resolvem no dossiê real ({com_log}/26)",
               com_log == len(C.SERVICOS))

    print("\nProgresso:")
    checar("progresso conta variáveis fechadas", f.progresso() == (1, 10))

    total = 26
    print(f"\n=== coding_flow: {len(falhas) and 'FALHOU' or 'ok'} "
          f"({total - len(falhas)}/{total}) ===")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(_self_test())
