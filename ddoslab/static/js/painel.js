"use strict";

const $ = (id) => document.getElementById(id);

const fmtInteiro = new Intl.NumberFormat("pt-BR");
const fmtDecimal = new Intl.NumberFormat("pt-BR", {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});
const fmtDataHora = new Intl.DateTimeFormat("pt-BR", {
  day: "2-digit",
  month: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});
const fmtHora = new Intl.DateTimeFormat("pt-BR", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

const appState = {
  dados: null,
  ultimoEstadoExperimento: null,
  ocupado: false,
  atualizando: false,
  falhasSeguidas: 0,
  redimensionamento: null,
};

const elementos = {};

document.addEventListener("DOMContentLoaded", iniciarPainel);

function iniciarPainel() {
  elementos.form = $("form-experimento");
  elementos.btnIniciar = $("btn-iniciar");
  elementos.btnParar = $("btn-parar");
  elementos.btnReiniciar = $("btn-reiniciar");
  elementos.btnLegitimo = $("btn-legitimo");
  elementos.protecao = $("protecao");
  elementos.estadoBadge = $("estado-badge");
  elementos.conexao = $("conexao");
  elementos.textoConexao = $("texto-conexao");
  elementos.textoProgresso = $("texto-progresso");
  elementos.tempoProgresso = $("tempo-progresso");
  elementos.barraProgresso = $("barra-progresso");
  elementos.mensagemControle = $("mensagem-controle");
  elementos.resultadoLegitimo = $("resultado-legitimo");
  elementos.tabelaClientes = $("tabela-clientes");
  elementos.comparacaoVazia = $("comparacao-vazia");
  elementos.comparacaoCartoes = $("comparacao-cartoes");
  elementos.comparacaoDelta = $("comparacao-delta");
  elementos.canvasLatencia = $("grafico-latencia");
  elementos.canvasResultados = $("grafico-resultados");
  elementos.seloLatencia = $("selo-latencia-texto");
  elementos.seloResultados = $("selo-resultados-texto");

  elementos.form.addEventListener("submit", iniciarExperimento);
  elementos.btnParar.addEventListener("click", pararExperimento);
  elementos.btnReiniciar.addEventListener("click", reiniciarLaboratorio);
  elementos.btnLegitimo.addEventListener("click", acessarServico);

  document.querySelectorAll('input[name="cenario"]').forEach((radio) => {
    radio.addEventListener("change", atualizarDetalhesCenario);
  });

  window.addEventListener("resize", () => {
    window.clearTimeout(appState.redimensionamento);
    appState.redimensionamento = window.setTimeout(() => {
      if (appState.dados) {
        desenharGraficos(appState.dados.metricas.serie_temporal);
      }
    }, 140);
  });

  buscarEstado();
  window.setInterval(buscarEstado, 1000);
}

async function buscarEstado() {
  if (appState.atualizando) {
    return;
  }
  appState.atualizando = true;
  const controlador = new AbortController();
  const limite = window.setTimeout(() => controlador.abort(), 4500);
  try {
    const resposta = await fetch("/api/estado", {
      cache: "no-store",
      headers: { Accept: "application/json" },
      signal: controlador.signal,
    });
    if (!resposta.ok) {
      throw new Error(`Falha de comunicação (${resposta.status}).`);
    }
    const dados = await resposta.json();
    appState.dados = dados;
    appState.falhasSeguidas = 0;
    definirConexao(true);
    renderizar(dados);
  } catch (erro) {
    appState.falhasSeguidas += 1;
    if (appState.falhasSeguidas >= 2) {
      definirConexao(false);
    }
  } finally {
    window.clearTimeout(limite);
    appState.atualizando = false;
  }
}

function definirConexao(ok) {
  if (!elementos.conexao) {
    return;
  }
  elementos.conexao.className = ok ? "selo selo-ok" : "selo selo-executando";
  elementos.textoConexao.textContent = ok
    ? "Painel atualizado a cada 1 s"
    : "Reconectando ao painel";
}

function renderizar(dados) {
  const experimento = dados.experimento;
  const estadoAnterior = appState.ultimoEstadoExperimento;

  renderizarEstado(experimento);
  sincronizarControles(experimento, estadoAnterior);
  renderizarProgresso(experimento);
  atualizarDetalhesCenario(experimento);
  renderizarKpis(dados.metricas);
  renderizarTabela(dados.metricas.por_cliente);
  renderizarComparacao(dados.comparacao);
  renderizarIndicadoresGraficos(experimento, dados.metricas.serie_temporal);
  desenharGraficos(dados.metricas.serie_temporal);

  appState.ultimoEstadoExperimento = experimento.estado;
}

function renderizarIndicadoresGraficos(experimento, serie) {
  const temAmostras = serie.some((ponto) => ponto.total > 0);
  const texto =
    experimento.estado === "executando"
      ? "Ao vivo"
      : temAmostras
      ? "Última janela"
      : "Aguardando";
  elementos.seloLatencia.textContent = texto;
  elementos.seloResultados.textContent = texto;
}

function renderizarEstado(experimento) {
  const rotulos = {
    ocioso: "Ocioso",
    executando: "Em execução",
    finalizado: "Finalizado",
  };
  elementos.estadoBadge.textContent =
    rotulos[experimento.estado] || experimento.estado;
  elementos.estadoBadge.className = "selo";
  if (experimento.estado === "executando") {
    elementos.estadoBadge.classList.add("selo-executando");
  } else if (experimento.estado === "finalizado") {
    elementos.estadoBadge.classList.add("selo-verde");
  } else {
    elementos.estadoBadge.classList.add("selo-neutro");
  }
}

function sincronizarControles(experimento, estadoAnterior) {
  const emExecucao = experimento.estado === "executando";

  if (emExecucao) {
    elementos.protecao.checked = Boolean(experimento.protecao_ativa);
    const cenario = experimento.cenario;
    if (cenario) {
      const radio = document.querySelector(
        `input[name="cenario"][value="${cenario.chave}"]`
      );
      if (radio) {
        radio.checked = true;
      }
    }
  } else if (estadoAnterior !== experimento.estado) {
    const cenario = experimento.cenario;
    if (cenario) {
      const radio = document.querySelector(
        `input[name="cenario"][value="${cenario.chave}"]`
      );
      if (radio) {
        radio.checked = true;
      }
    }
    if (experimento.estado === "ocioso") {
      elementos.protecao.checked = false;
    } else if (experimento.estado === "finalizado") {
      elementos.protecao.checked = Boolean(experimento.protecao_ativa);
    }
  }

  document.querySelectorAll('input[name="cenario"]').forEach((radio) => {
    radio.disabled = emExecucao || appState.ocupado;
  });
  elementos.protecao.disabled = emExecucao || appState.ocupado;

  elementos.btnIniciar.disabled = emExecucao || appState.ocupado;
  elementos.btnParar.disabled = !emExecucao || appState.ocupado;
  elementos.btnReiniciar.disabled = appState.ocupado;
}

function renderizarProgresso(experimento) {
  if (experimento.estado === "executando" && experimento.cenario) {
    const duracao = Number(experimento.cenario.duracao_s) || 1;
    const decorrido = Number(experimento.decorrido_s) || 0;
    const restante = Number(experimento.restante_s) || 0;
    const percentual = Math.min(100, Math.max(0, (decorrido / duracao) * 100));
    elementos.barraProgresso.value = percentual;
    elementos.textoProgresso.textContent = `Carga em andamento · ${experimento.cenario.rotulo} · proteção ${
      experimento.protecao_ativa ? "ativa" : "inativa"
    }`;
    elementos.tempoProgresso.textContent = `${fmtDecimal.format(restante)} s restantes`;
    return;
  }

  if (experimento.estado === "finalizado") {
    const motivo =
      experimento.motivo_encerramento === "manual"
        ? "interrompido manualmente"
        : "concluído pelo tempo";
    elementos.barraProgresso.value = 100;
    elementos.textoProgresso.textContent = `Execução finalizada · ${motivo}`;
    const medido = experimento.duracao_medida_s;
    elementos.tempoProgresso.textContent =
      medido === null || medido === undefined
        ? "—"
        : `${fmtDecimal.format(Number(medido))} s medidos`;
    return;
  }

  elementos.barraProgresso.value = 0;
  elementos.textoProgresso.textContent = "Pronto para iniciar.";
  elementos.tempoProgresso.textContent = "0,0 s";
}

function cenarioSelecionado(experimento) {
  if (experimento && experimento.cenario) {
    return experimento.cenario;
  }
  if (!appState.dados) {
    return null;
  }
  const selecionado = document.querySelector(
    'input[name="cenario"]:checked'
  );
  const chave = selecionado ? selecionado.value : null;
  return appState.dados.cenarios.find((item) => item.chave === chave) || null;
}

function atualizarDetalhesCenario(experimento) {
  if (!appState.dados) {
    return;
  }
  const cenario = cenarioSelecionado(experimento);
  if (!cenario) {
    return;
  }
  const servidor = appState.dados.servidor;
  const limites = appState.dados.limites;
  const protecaoAtiva =
    experimento.estado === "executando" || experimento.estado === "finalizado"
      ? Boolean(experimento.protecao_ativa)
      : elementos.protecao.checked;

  $("detalhe-clientes").textContent = `${cenario.clientes_virtuais} virtuais + 1 sonda`;
  $("detalhe-taxa").textContent = `${cenario.taxa_por_cliente} req/s por cliente`;
  $("detalhe-duracao").textContent = `${cenario.duracao_s} segundos`;
  $("detalhe-volume").textContent = `${fmtInteiro.format(
    cenario.total_planejado
  )} requisições`;
  $("detalhe-capacidade").textContent = `${servidor.capacidade.ocupadas}/${
    servidor.capacidade.maximo
  } ocupadas · ${fmtDecimal.format(
    Number(servidor.capacidade_teorica_por_s)
  )} req/s teóricos`;
  $("detalhe-protecao").textContent = protecaoAtiva
    ? `Ativa · ${fmtDecimal.format(
        Number(limites.limite_por_cliente_s)
      )} req/s por cliente`
    : "Inativa";

  const chips = $("chips-clientes");
  chips.replaceChildren();
  for (let indice = 1; indice <= cenario.clientes_virtuais; indice += 1) {
    const chip = document.createElement("span");
    chip.className = "chip-cliente";
    chip.textContent = `virtual-${String(indice).padStart(2, "0")}`;
    chips.appendChild(chip);
  }
  const sonda = document.createElement("span");
  sonda.className = "chip-cliente legitimo";
  sonda.textContent = "sonda-legitima";
  chips.appendChild(sonda);
}

function renderizarKpis(metricas) {
  const total = metricas.total;
  const legitimo = metricas.por_papel.legitimo;

  $("kpi-sucesso").textContent = fmtInteiro.format(total.sucesso);
  $("kpi-sucesso-taxa").textContent = `${fmtDecimal.format(
    Number(total.taxa_sucesso)
  )}% do total contabilizado`;

  $("kpi-rejeitado").textContent = fmtInteiro.format(total.rejeitado);

  $("kpi-falhas").textContent = fmtInteiro.format(
    total.falhas_disponibilidade
  );
  $("kpi-falhas-detalhe").textContent = `${fmtInteiro.format(
    total.falha_capacidade
  )} HTTP 503 · ${fmtInteiro.format(
    total.falha_transporte
  )} falhas de transporte`;

  $("kpi-p95").textContent = formatarMs(total.latencia_p95_ms);

  $("kpi-legitimo").textContent =
    legitimo.total > 0 ? `${fmtDecimal.format(Number(legitimo.taxa_sucesso))}%` : "—";
  $("kpi-legitimo-detalhe").textContent =
    legitimo.total > 0
      ? `${fmtInteiro.format(legitimo.sucesso)} de ${fmtInteiro.format(
          legitimo.total
        )} amostras com sucesso`
      : "sem amostras";

  $("kpi-total").textContent = fmtInteiro.format(total.total);
  $("kpi-total-detalhe").textContent =
    total.total > 0
      ? `${fmtInteiro.format(total.total)} respostas e falhas`
      : "aguardando requisições";
}

function renderizarTabela(clientes) {
  const corpo = elementos.tabelaClientes;
  corpo.replaceChildren();

  if (!clientes.length) {
    const linha = document.createElement("tr");
    const celula = document.createElement("td");
    celula.colSpan = 7;
    celula.className = "vazio-tabela";
    celula.textContent = "Aguardando requisições medidas.";
    linha.appendChild(celula);
    corpo.appendChild(linha);
    return;
  }

  clientes.forEach((cliente) => {
    const linha = document.createElement("tr");

    const id = document.createElement("td");
    const idTexto = document.createElement("span");
    idTexto.className = "cliente-id";
    idTexto.textContent = cliente.cliente;
    id.appendChild(idTexto);

    const papel = document.createElement("td");
    const etiqueta = document.createElement("span");
    etiqueta.className = `papel papel-${cliente.papel}`;
    etiqueta.textContent = cliente.papel_rotulo;
    papel.appendChild(etiqueta);

    linha.appendChild(id);
    linha.appendChild(papel);
    linha.appendChild(celulaNumero(cliente.total));
    linha.appendChild(celulaNumero(cliente.sucesso));
    linha.appendChild(celulaNumero(cliente.rejeitado));
    linha.appendChild(
      celulaNumero(cliente.falha_capacidade + cliente.falha_transporte)
    );
    linha.appendChild(celulaNumero(formatarMs(cliente.latencia_p95_ms)));
    corpo.appendChild(linha);
  });
}

function celulaNumero(valor) {
  const celula = document.createElement("td");
  celula.className = "numero";
  celula.textContent =
    typeof valor === "number" ? fmtInteiro.format(valor) : String(valor);
  return celula;
}

function formatarMs(valor) {
  if (valor === null || valor === undefined || Number.isNaN(Number(valor))) {
    return "—";
  }
  return `${fmtDecimal.format(Number(valor))} ms`;
}

function renderizarComparacao(comparacao) {
  const com = comparacao.com_protecao;
  const sem = comparacao.sem_protecao;

  if (!com && !sem) {
    elementos.comparacaoVazia.hidden = false;
    elementos.comparacaoCartoes.hidden = true;
    elementos.comparacaoDelta.hidden = true;
    return;
  }

  elementos.comparacaoVazia.hidden = true;
  elementos.comparacaoCartoes.hidden = false;
  preencherResumoComparacao("sem", sem);
  preencherResumoComparacao("com", com);

  if (!com || !sem) {
    elementos.comparacaoDelta.hidden = true;
    return;
  }

  const legitimoCom = com.legitimo || {};
  const legitimoSem = sem.legitimo || {};
  if (!(legitimoCom.total > 0) || !(legitimoSem.total > 0)) {
    elementos.comparacaoDelta.hidden = true;
    return;
  }

  const diferenca =
    Number(legitimoCom.taxa_sucesso) - Number(legitimoSem.taxa_sucesso);
  const sentido =
    Math.abs(diferenca) < 0.05
      ? "ficou praticamente igual"
      : diferenca > 0
      ? `foi ${fmtDecimal.format(Math.abs(diferenca))} p.p. maior`
      : `foi ${fmtDecimal.format(Math.abs(diferenca))} p.p. menor`;

  const cenariosDiferentes =
    com.cenario && sem.cenario && com.cenario.chave !== sem.cenario.chave;
  const partes = [
    `Com base nas execuções medidas, a taxa de sucesso da sonda legítima ${sentido} com a proteção ativa.`,
    `Latência p95 da sonda: ${formatarMs(
      legitimoCom.latencia_p95_ms
    )} com proteção e ${formatarMs(legitimoSem.latencia_p95_ms)} sem proteção.`,
  ];
  if (cenariosDiferentes) {
    partes.unshift(
      "Atenção: as duas execuções usaram cenários diferentes, então a comparação é apenas indicativa."
    );
  }

  elementos.comparacaoDelta.textContent = partes.join(" ");
  elementos.comparacaoDelta.classList.toggle("alerta", cenariosDiferentes);
  elementos.comparacaoDelta.hidden = false;
}

function preencherResumoComparacao(prefixo, resumo) {
  const legitimo = resumo ? resumo.legitimo || {} : null;
  const taxa = legitimo && legitimo.total > 0 ? legitimo.taxa_sucesso : null;
  const p95 = legitimo ? legitimo.latencia_p95_ms : null;
  const falhas = legitimo ? legitimo.falhas_disponibilidade : null;
  const rejeicoes = legitimo ? legitimo.rejeitado : null;

  $(`comp-${prefixo}-taxa`).textContent =
    taxa === null ? "—" : `${fmtDecimal.format(Number(taxa))}%`;
  $(`comp-${prefixo}-p95`).textContent = formatarMs(p95);
  $(`comp-${prefixo}-falhas`).textContent =
    falhas === null ? "—" : fmtInteiro.format(falhas);
  $(`comp-${prefixo}-rejeicoes`).textContent =
    rejeicoes === null ? "—" : fmtInteiro.format(rejeicoes);
  $(`comp-${prefixo}-cenario`).textContent = resumo
    ? resumo.cenario.rotulo
    : "—";

  const quando = $(`comp-${prefixo}-quando`);
  if (!resumo) {
    quando.textContent = "Ainda não executado";
    return;
  }
  const data = formatarDataHora(resumo.finalizado_em);
  const amostras =
    legitimo && legitimo.total > 0
      ? `${fmtInteiro.format(legitimo.total)} amostras da sonda`
      : "sem amostras da sonda";
  quando.textContent = `${data} · ${amostras}`;
}

function formatarDataHora(valor) {
  if (!valor) {
    return "—";
  }
  const data = new Date(valor);
  if (Number.isNaN(data.getTime())) {
    return "—";
  }
  return fmtDataHora.format(data);
}

async function acessarServico() {
  if (elementos.btnLegitimo.disabled) {
    return;
  }
  elementos.btnLegitimo.disabled = true;
  elementos.btnLegitimo.textContent = "Consultando o serviço…";
  const inicio = performance.now();

  try {
    const resposta = await fetch("/api/servico", {
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    const duracao = performance.now() - inicio;
    let corpo = {};
    try {
      corpo = await resposta.json();
    } catch (_erro) {
      corpo = {};
    }

    if (resposta.status === 200) {
      mostrarResultadoLegitimo(
        "ok",
        "Serviço disponível",
        duracao,
        `HTTP 200 · processamento sintético de ${
          corpo.processamento_simulado_ms ?? "—"
        } ms`
      );
    } else if (resposta.status === 429) {
      mostrarResultadoLegitimo(
        "alerta",
        "Requisição limitada",
        duracao,
        "HTTP 429 · o limitador deste cliente recusou a requisição."
      );
    } else if (resposta.status === 503) {
      mostrarResultadoLegitimo(
        "erro",
        "Serviço indisponível",
        duracao,
        "HTTP 503 · a capacidade de atendimento estava esgotada."
      );
    } else {
      mostrarResultadoLegitimo(
        "erro",
        `Resposta HTTP ${resposta.status}`,
        duracao,
        corpo.mensagem || "Resposta inesperada do serviço."
      );
    }
  } catch (_erro) {
    const duracao = performance.now() - inicio;
    mostrarResultadoLegitimo(
      "erro",
      "Falha de transporte",
      duracao,
      "O navegador não conseguiu concluir a requisição ao serviço local."
    );
  } finally {
    elementos.btnLegitimo.disabled = false;
    elementos.btnLegitimo.textContent = "Acessar o serviço agora";
    buscarEstado();
  }
}

function mostrarResultadoLegitimo(tipo, titulo, duracao, detalhe) {
  const caixa = document.createElement("div");
  caixa.className = "resultado-item";

  const topo = document.createElement("div");
  topo.className = "resultado-topo";

  const status = document.createElement("span");
  status.className = `status-resultado status-${tipo}`;
  status.textContent = titulo;

  const tempo = document.createElement("span");
  tempo.className = "resultado-tempo";
  tempo.textContent = `${fmtDecimal.format(duracao)} ms`;

  const texto = document.createElement("p");
  texto.className = "resultado-detalhe";
  texto.textContent = `Medição do navegador: ${detalhe}`;

  topo.appendChild(status);
  topo.appendChild(tempo);
  caixa.appendChild(topo);
  caixa.appendChild(texto);
  elementos.resultadoLegitimo.replaceChildren(caixa);
}

async function iniciarExperimento(evento) {
  evento.preventDefault();
  if (appState.ocupado) {
    return;
  }
  const selecionado = document.querySelector(
    'input[name="cenario"]:checked'
  );
  if (!selecionado) {
    mostrarMensagem("Selecione um cenário antes de iniciar.", "erro");
    return;
  }

  appState.ocupado = true;
  sincronizarControles(
    appState.dados?.experimento || { estado: "ocioso" },
    appState.ultimoEstadoExperimento
  );
  elementos.btnIniciar.textContent = "Iniciando…";
  mostrarMensagem("", null);

  try {
    const dados = await enviarComando("/api/experimento/iniciar", {
      cenario: selecionado.value,
      protecao: elementos.protecao.checked,
    });
    mostrarMensagem(
      dados.mensagem ||
        "Experimento iniciado. Acompanhe as métricas em tempo real.",
      "sucesso"
    );
    await buscarEstado();
  } catch (erro) {
    mostrarMensagem(erro.message, "erro");
  } finally {
    appState.ocupado = false;
    elementos.btnIniciar.textContent = "Iniciar experimento";
    if (appState.dados) {
      renderizar(appState.dados);
    }
  }
}

async function pararExperimento() {
  if (appState.ocupado) {
    return;
  }
  appState.ocupado = true;
  elementos.btnParar.textContent = "Parando…";
  sincronizarControles(
    appState.dados?.experimento || { estado: "ocioso" },
    appState.ultimoEstadoExperimento
  );

  try {
    const dados = await enviarComando("/api/experimento/parar");
    mostrarMensagem(
      dados.mensagem || "Experimento interrompido.",
      "sucesso"
    );
    await buscarEstado();
  } catch (erro) {
    mostrarMensagem(erro.message, "erro");
  } finally {
    appState.ocupado = false;
    elementos.btnParar.textContent = "Parar";
    if (appState.dados) {
      renderizar(appState.dados);
    }
  }
}

async function reiniciarLaboratorio() {
  if (appState.ocupado) {
    return;
  }
  const confirmado = window.confirm(
    "Reiniciar o laboratório apaga todas as métricas e a comparação atual. Deseja continuar?"
  );
  if (!confirmado) {
    return;
  }
  appState.ocupado = true;
  elementos.btnReiniciar.textContent = "Reiniciando…";
  sincronizarControles(
    appState.dados?.experimento || { estado: "ocioso" },
    appState.ultimoEstadoExperimento
  );

  try {
    const dados = await enviarComando("/api/laboratorio/reiniciar");
    mostrarMensagem(
      dados.mensagem || "Laboratório reiniciado.",
      "sucesso"
    );
    await buscarEstado();
  } catch (erro) {
    mostrarMensagem(erro.message, "erro");
  } finally {
    appState.ocupado = false;
    elementos.btnReiniciar.textContent = "Reiniciar laboratório";
    if (appState.dados) {
      renderizar(appState.dados);
    }
  }
}

async function enviarComando(url, corpo) {
  const opcoes = {
    method: "POST",
    cache: "no-store",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(corpo || {}),
  };
  const resposta = await fetch(url, opcoes);
  let dados = {};
  try {
    dados = await resposta.json();
  } catch (_erro) {
    dados = {};
  }
  if (!resposta.ok) {
    throw new Error(
      dados.erro || `Não foi possível concluir a ação (HTTP ${resposta.status}).`
    );
  }
  return dados;
}

function mostrarMensagem(texto, tipo) {
  const caixa = elementos.mensagemControle;
  if (!texto) {
    caixa.hidden = true;
    caixa.textContent = "";
    caixa.className = "mensagem";
    return;
  }
  caixa.textContent = texto;
  caixa.className = `mensagem mensagem-${tipo === "erro" ? "erro" : "sucesso"}`;
  caixa.hidden = false;
}

function desenharGraficos(serie) {
  desenharGraficoLatencia(serie);
  desenharGraficoResultados(serie);
}

function prepararCanvas(canvas) {
  if (!canvas) {
    return null;
  }
  const largura = canvas.clientWidth;
  const altura = canvas.clientHeight;
  if (largura < 20 || altura < 20) {
    return null;
  }
  const proporcao = window.devicePixelRatio || 1;
  const novaLargura = Math.round(largura * proporcao);
  const novaAltura = Math.round(altura * proporcao);
  if (canvas.width !== novaLargura || canvas.height !== novaAltura) {
    canvas.width = novaLargura;
    canvas.height = novaAltura;
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(proporcao, 0, 0, proporcao, 0, 0);
  ctx.clearRect(0, 0, largura, altura);
  return { ctx, largura, altura };
}

function desenharGraficoLatencia(serie) {
  const preparado = prepararCanvas(elementos.canvasLatencia);
  if (!preparado) {
    return;
  }
  const { ctx, largura, altura } = preparado;
  const margem = { topo: 16, direita: 12, baixo: 28, esquerda: 48 };
  const areaLargura = largura - margem.esquerda - margem.direita;
  const areaAltura = altura - margem.topo - margem.baixo;
  const temDados = serie.some(
    (ponto) =>
      ponto.latencia_media_ms !== null || ponto.latencia_p95_ms !== null
  );

  const valores = [];
  serie.forEach((ponto) => {
    if (ponto.latencia_media_ms !== null) {
      valores.push(Number(ponto.latencia_media_ms));
    }
    if (ponto.latencia_p95_ms !== null) {
      valores.push(Number(ponto.latencia_p95_ms));
    }
  });
  const maximo = escalaAgradavel(Math.max(10, ...valores));
  desenharEixos(
    ctx,
    margem,
    areaLargura,
    areaAltura,
    maximo,
    (valor) => `${Math.round(valor)} ms`,
    serie
  );

  if (!temDados) {
    desenharMensagemCentral(
      ctx,
      largura,
      altura,
      "Aguardando respostas bem-sucedidas para medir a latência."
    );
    return;
  }

  const pontosMedia = [];
  const pontosP95 = [];
  serie.forEach((ponto, indice) => {
    const x =
      margem.esquerda +
      (serie.length === 1 ? 0 : (indice / (serie.length - 1)) * areaLargura);
    pontosMedia.push(
      ponto.latencia_media_ms === null
        ? { x, y: null }
        : {
            x,
            y:
              margem.topo +
              areaAltura -
              (Number(ponto.latencia_media_ms) / maximo) * areaAltura,
          }
    );
    pontosP95.push(
      ponto.latencia_p95_ms === null
        ? { x, y: null }
        : {
            x,
            y:
              margem.topo +
              areaAltura -
              (Number(ponto.latencia_p95_ms) / maximo) * areaAltura,
          }
    );
  });

  desenharLinha(ctx, pontosMedia, "#2dd4bf", 2.2, []);
  desenharLinha(ctx, pontosP95, "#fbbf24", 1.6, [4, 4]);
}

function desenharGraficoResultados(serie) {
  const preparado = prepararCanvas(elementos.canvasResultados);
  if (!preparado) {
    return;
  }
  const { ctx, largura, altura } = preparado;
  const margem = { topo: 16, direita: 12, baixo: 28, esquerda: 44 };
  const areaLargura = largura - margem.esquerda - margem.direita;
  const areaAltura = altura - margem.topo - margem.baixo;
  const maximo = escalaAgradavel(
    Math.max(5, ...serie.map((ponto) => Number(ponto.total) || 0))
  );

  desenharEixos(
    ctx,
    margem,
    areaLargura,
    areaAltura,
    maximo,
    (valor) => `${Math.round(valor)}`,
    serie
  );

  const temDados = serie.some((ponto) => ponto.total > 0);
  if (!temDados) {
    desenharMensagemCentral(
      ctx,
      largura,
      altura,
      "Aguardando requisições para desenhar os resultados."
    );
    return;
  }

  const espaco = areaLargura / serie.length;
  const larguraBarra = Math.max(2, espaco * 0.62);
  const cores = ["#2dd4bf", "#fbbf24", "#fb7185"];

  serie.forEach((ponto, indice) => {
    const x = margem.esquerda + indice * espaco + (espaco - larguraBarra) / 2;
    const segmentos = [
      Number(ponto.sucesso) || 0,
      Number(ponto.rejeitado) || 0,
      Number(ponto.falhas) || 0,
    ];
    let acumulado = 0;
    segmentos.forEach((valor, posicao) => {
      if (!valor) {
        return;
      }
      const alturaBarra = (valor / maximo) * areaAltura;
      const y =
        margem.topo + areaAltura - ((acumulado + valor) / maximo) * areaAltura;
      ctx.fillStyle = cores[posicao];
      ctx.globalAlpha = 0.88;
      ctx.fillRect(x, y, larguraBarra, Math.max(1, alturaBarra));
      ctx.globalAlpha = 1;
      acumulado += valor;
    });
  });
}

function desenharEixos(ctx, margem, areaLargura, areaAltura, maximo, rotuloY, serie) {
  const linhas = 4;
  ctx.save();
  ctx.font = '11px "Segoe UI", sans-serif';
  ctx.textBaseline = "middle";
  for (let indice = 0; indice <= linhas; indice += 1) {
    const fracao = indice / linhas;
    const y = margem.topo + areaAltura - fracao * areaAltura;
    ctx.strokeStyle = "rgba(168, 187, 209, 0.10)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(margem.esquerda, y + 0.5);
    ctx.lineTo(margem.esquerda + areaLargura, y + 0.5);
    ctx.stroke();
    ctx.fillStyle = "rgba(120, 144, 171, 0.9)";
    ctx.textAlign = "right";
    ctx.fillText(rotuloY(maximo * fracao), margem.esquerda - 7, y);
  }

  if (serie.length) {
    ctx.fillStyle = "rgba(120, 144, 171, 0.9)";
    ctx.textBaseline = "top";
    const indices = [0, Math.floor((serie.length - 1) / 2), serie.length - 1];
    indices.forEach((indice, posicao) => {
      const x =
        margem.esquerda +
        (serie.length === 1
          ? 0
          : (indice / (serie.length - 1)) * areaLargura);
      ctx.textAlign = posicao === 0 ? "left" : posicao === 2 ? "right" : "center";
      const data = new Date(serie[indice].segundo * 1000);
      ctx.fillText(
        fmtHora.format(data),
        x,
        margem.topo + areaAltura + 9
      );
    });
  }
  ctx.restore();
}

function desenharLinha(ctx, pontos, cor, espessura, tracejado) {
  ctx.save();
  ctx.strokeStyle = cor;
  ctx.lineWidth = espessura;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.setLineDash(tracejado);
  let desenhando = false;
  pontos.forEach((ponto) => {
    if (ponto.y === null) {
      desenhando = false;
      return;
    }
    if (!desenhando) {
      ctx.beginPath();
      ctx.moveTo(ponto.x, ponto.y);
      desenhando = true;
    } else {
      ctx.lineTo(ponto.x, ponto.y);
    }
  });
  ctx.stroke();
  ctx.restore();
}

function desenharMensagemCentral(ctx, largura, altura, mensagem) {
  ctx.save();
  ctx.fillStyle = "rgba(120, 144, 171, 0.92)";
  ctx.font = '12px "Segoe UI", sans-serif';
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(mensagem, largura / 2, altura / 2);
  ctx.restore();
}

function escalaAgradavel(valor) {
  if (!Number.isFinite(valor) || valor <= 0) {
    return 10;
  }
  const potencia = Math.pow(10, Math.floor(Math.log10(valor)));
  const base = valor / potencia;
  let fator = 10;
  if (base <= 1) {
    fator = 1;
  } else if (base <= 2) {
    fator = 2;
  } else if (base <= 5) {
    fator = 5;
  }
  return fator * potencia;
}
