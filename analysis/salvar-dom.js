/* Salva o DOM RENDERIZADO da página aberta, com a URL gravada dentro do arquivo.
 *
 * Uso: abra a página com a VPN da UE ligada, espere carregar por completo,
 * DevTools (⌥⌘I) > Console, cole isto inteiro e dê Enter. O arquivo cai em
 * ~/Downloads e o nome não importa — quem identifica o documento é o marcador
 * FREEZE-SOURCE na primeira linha, que o `adopt` lê sozinho.
 *
 * Precisa ser o DOM e não o código-fonte: Temu, Shein e afins montam a página
 * por JS, e "Exibir código-fonte" devolve o shell vazio.
 */
(() => {
  const texto = (document.body && document.body.innerText || "").trim();
  if (texto.length < 1000 &&
      !confirm(`Esta página rende só ${texto.length} caracteres de texto.\n\n` +
               `Provavelmente ainda não terminou de carregar, ou exige rolar/` +
               `aceitar algo antes de mostrar o conteúdo.\n\nSalvar assim mesmo?`))
    return "cancelado — espere carregar e rode de novo";

  const url = location.href;
  const conteudo = `<!-- FREEZE-SOURCE ${url} -->\n` +
                   `<!-- FREEZE-CAPTURED ${new Date().toISOString()} -->\n` +
                   document.documentElement.outerHTML;

  const nome = (location.hostname + location.pathname + location.hash)
      .replace(/[^a-z0-9]+/gi, "-").replace(/^-+|-+$/g, "").slice(0, 90) + ".html";

  try {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([conteudo], { type: "text/html" }));
    a.download = nome;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    return `salvo: ${nome} (${texto.length} caracteres de texto)`;
  } catch (e) {
    // Alguns sites bloqueiam blob: por CSP. Aí vai pela área de transferência:
    // copie o retorno e, no terminal:  pbpaste > ~/Downloads/pagina.html
    copy(conteudo);
    return `CSP bloqueou o download (${e.message}). O conteúdo foi para a área ` +
           `de transferência — no terminal: pbpaste > ~/Downloads/${nome}`;
  }
})()
