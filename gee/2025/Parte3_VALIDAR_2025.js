// ====================================================================
// LULC + NDBI - BACIA DO RIO MATHIAS ALMADA | ANO 2025
// PARTE 3 - VALIDAR: ACURÁCIA E ÁREAS AJUSTADAS (OLOFSSON et al., 2014)
//
// Import necessário: table (limite da bacia, o mesmo usado no MAPEAR).
//
// Lê:
//   - o mapa exportado no MAPEAR (asset LULC_MathiasAlmada_2025, bandas
//     'classification' e 'NDBI_bin');
//   - os pontos rotulados às cegas:
//       Pontos_Validacao_LULC_MathiasAlmada_2025  (coluna ref_classe: 1 a 5)
//       Pontos_Validacao_NDBI_MathiasAlmada_2025  (coluna ref_NDBI: 0 ou 1)
//
// Gera (console + CSV no Drive), para LULC e para NDBI:
//   T1  Matriz de confusão amostral (contagens)
//   T2  Matriz em % por linha (visão do usuário) e T3 em % por coluna (produtor)
//   T4  Matriz de proporções de área estimadas (p_ij de Olofsson)
//   T5  Métricas por classe amostrais (UA, PA, F1, IoU, especificidade, Kappa condicional)
//   T6  Métricas por classe ajustadas por área + áreas ajustadas com IC 95%
//   T7  Métricas globais (OA amostral e ponderada com IC, Kappa, F1 macro, QD, AD)
//   T8  Acurácia por fonte/data da imagem de referência (se as colunas existirem)
//   T9  Pares referência x mapa com acerto (CSV e SHP para mapear os erros no QGIS)
//
// AGRUPAMENTO (AGRUPAR = true): após a validação com 5 classes, Vegetação
// Rasteira (2) e Solo Exposto (4) são unidas em "Vegetação rasteira e solo
// exposto" (código 2), no MAPA e na REFERÊNCIA, com os MESMOS pontos. Unir
// estratos mantém válido o desenho estratificado (Olofsson et al., 2014).
// A estratificação original (50/50/20/50/50) é conferida ANTES do agrupamento.
// ====================================================================

// ============================
// 1 - PARÂMETROS
// ============================
var ANO = 2025;
var AREA = 'MathiasAlmada';
var DESC = AREA + '_' + ANO;
var PASTA = 'LULC_' + DESC;
var ASSET_BASE = 'projects/SEU-PROJETO-GEE/assets/';   // <- troque pelo seu projeto do Earth Engine

var ASSET_SUFIXO = '_v2';  // o MESMO usado no MAPEAR (mapa v2, amostras revisadas)
var ASSET_MAPA = ASSET_BASE + 'LULC_' + DESC + ASSET_SUFIXO;
// Pontos rotulados de 2025 (versão _v2 do mapa). O script procura primeiro o nome
// com _v2 (igual ao CSV exportado) e, se não existir, o nome sem _v2.
function primeiroAssetExistente(nomes) {
  for (var i = 0; i < nomes.length; i++) {
    try { if (ee.data.getAsset(nomes[i])) { return nomes[i]; } } catch (e) {}
  }
  return nomes[0];
}
var ASSET_PONTOS_LULC = primeiroAssetExistente([
  ASSET_BASE + 'Pontos_Validacao_LULC' + ASSET_SUFIXO + '_' + DESC,
  ASSET_BASE + 'Pontos_Validacao_LULC_' + DESC]);
var ASSET_PONTOS_NDBI = primeiroAssetExistente([
  ASSET_BASE + 'Pontos_Validacao_NDBI' + ASSET_SUFIXO + '_' + DESC,
  ASSET_BASE + 'Pontos_Validacao_NDBI_' + DESC]);

var COL_REF_LULC = 'ref_classe';
var COL_REF_NDBI = 'ref_NDBI';

// Colunas de fonte e data da imagem de referência. null = detecção automática
// (procura nomes com "fonte/source/imagem/sensor" e "data/date").
var COL_FONTE = null;
var COL_DATA = null;

// Agrupamento de classes do LULC (aplicar o MESMO em 2025)
var AGRUPAR = true;
var REMAP_DE   = [1, 2, 3, 4, 5];
var REMAP_PARA = [1, 2, 3, 2, 5];   // 4 (Solo Exposto) -> 2

// Estratificação usada no sorteio (NÃO ALTERAR: igual ao MAPEAR)
var N_PONTOS = [50, 50, 20, 50, 50];
var N_PONTOS_NDBI = [50, 50];

var VALIDAR_LULC = true;
var VALIDAR_NDBI = true;

var Z = 1.96;                                     // IC de 95%
var LIM_OA = 85; var LIM_KAPPA = 0.60; var LIM_CLASSE = 70;

var CRS = 'EPSG:32721';
var ESCALA = 10;

var CFG_LULC = AGRUPAR ? {
  rotulo: 'LULC4cl', banda: 'classification', colRef: COL_REF_LULC, nPontos: N_PONTOS,
  asset: ASSET_PONTOS_LULC, idsSorteio: [1, 2, 3, 4, 5], remap: {de: REMAP_DE, para: REMAP_PARA},
  ids: [1, 2, 3, 5],
  nomes: ['Vegetação Densa', 'Vegetação rasteira e solo exposto', 'Água', 'Área Urbana']
} : {
  rotulo: 'LULC', banda: 'classification', colRef: COL_REF_LULC, nPontos: N_PONTOS,
  asset: ASSET_PONTOS_LULC, idsSorteio: [1, 2, 3, 4, 5], remap: null, ids: [1, 2, 3, 4, 5],
  nomes: ['Vegetação Densa', 'Vegetação Rasteira', 'Água', 'Solo Exposto', 'Área Urbana']
};
var CFG_NDBI = {
  rotulo: 'NDBI', banda: 'NDBI_bin', colRef: COL_REF_NDBI, nPontos: N_PONTOS_NDBI,
  asset: ASSET_PONTOS_NDBI, idsSorteio: [0, 1], remap: null, ids: [0, 1],
  nomes: ['Não construído', 'Construído/impermeável']
};
var PALETA = ['006400', 'ADFF2F', '0000FF', 'D2691E', 'FF0000'];
var PALETA_4CL = ['006400', 'C8B560', '0000FF', 'FF0000'];   // 1, 2, 3, 5 (classe 4 vazia)

var aoi = table.geometry();
Map.centerObject(aoi, 13);
Map.setOptions('SATELLITE');

// ============================
// 2 - FUNÇÕES ESTATÍSTICAS (JavaScript puro)
// ============================
function soma(a) { var s = 0, t; for (t = 0; t < a.length; t++) { s += a[t]; } return s; }
function lim(x, d) { if (!isFinite(x)) { return null; } var f = Math.pow(10, d); return Math.round(x * f) / f; }
function dividir(a, b) { return b > 0 ? a / b : NaN; }
function mediaValidos(a) {
  var s = 0, c = 0, t;
  for (t = 0; t < a.length; t++) { if (isFinite(a[t])) { s += a[t]; c++; } }
  return c > 0 ? s / c : NaN;
}
// errorMatrix do GEE: linhas = referência, colunas = mapa. Aqui m[i][j]: i = MAPA, j = REFERÊNCIA.
function transpor(m) {
  var t = [], i, j;
  for (i = 0; i < m.length; i++) { t.push([]); for (j = 0; j < m.length; j++) { t[i].push(m[j][i]); } }
  return t;
}
function rotuloKappa(k) {
  if (!isFinite(k)) { return null; }
  if (k < 0) { return 'Pobre'; } if (k <= 0.20) { return 'Leve'; } if (k <= 0.40) { return 'Razoável'; }
  if (k <= 0.60) { return 'Moderada'; } if (k <= 0.80) { return 'Substancial'; } return 'Quase perfeita';
}
// Discordância de quantidade e de alocação (Pontius e Millones, 2011)
function qdAd(m) {
  var n = m.length, tot = 0, diag = 0, dif = 0, i, j;
  for (i = 0; i < n; i++) { for (j = 0; j < n; j++) { tot += m[i][j]; } }
  for (i = 0; i < n; i++) {
    var linha = 0, coluna = 0;
    for (j = 0; j < n; j++) { linha += m[i][j]; coluna += m[j][i]; }
    diag += m[i][i]; dif += Math.abs(linha - coluna);
  }
  var qd = dif / (2 * tot);
  return {qd: qd, ad: (1 - diag / tot) - qd};
}
// Matriz em % por linha (porLinha = true) ou por coluna
function matrizPct(n, porLinha) {
  var K = n.length, m = [], i, j;
  for (i = 0; i < K; i++) {
    m.push([]);
    for (j = 0; j < K; j++) {
      var tot = 0, k;
      for (k = 0; k < K; k++) { tot += porLinha ? n[i][k] : n[k][j]; }
      m[i].push(tot > 0 ? 100 * n[i][j] / tot : 0);
    }
  }
  return m;
}

function metricasAmostrais(n, rotulo, cfg) {
  var K = cfg.ids.length, ni = [], nj = [], N = 0, i, j;
  for (i = 0; i < K; i++) { ni[i] = soma(n[i]); N += ni[i]; }
  for (j = 0; j < K; j++) { nj[j] = 0; for (i = 0; i < K; i++) { nj[j] += n[i][j]; } }
  var diag = 0, pe = 0;
  for (i = 0; i < K; i++) { diag += n[i][i]; pe += ni[i] * nj[i]; }
  var oa = diag / N;
  var kappa = (oa - pe / (N * N)) / (1 - pe / (N * N));
  var seOAs = Math.sqrt(oa * (1 - oa) / (N - 1));
  var UA = [], PA = [], F1 = [], feats = [];
  for (j = 0; j < K; j++) {
    var VP = n[j][j], FP = ni[j] - VP, FN = nj[j] - VP, VN = N - VP - FP - FN;
    var ua = dividir(VP, ni[j]), pa = dividir(VP, nj[j]);
    var f1 = (ua + pa) > 0 ? 2 * ua * pa / (ua + pa) : NaN;
    UA.push(ua); PA.push(pa); F1.push(f1);
    feats.push(ee.Feature(null, {
      conjunto: rotulo, ano: ANO, classe_id: cfg.ids[j], classe_nome: cfg.nomes[j],
      n_mapa: ni[j], n_referencia: nj[j], VP: VP, FP: FP, FN: FN, VN: VN,
      UA_pct: lim(ua * 100, 2), UA_IC95_pct: lim(Z * Math.sqrt(dividir(ua * (1 - ua), ni[j] - 1)) * 100, 2),
      erro_comissao_pct: lim((1 - ua) * 100, 2),
      PA_pct: lim(pa * 100, 2), PA_IC95_pct: lim(Z * Math.sqrt(dividir(pa * (1 - pa), nj[j] - 1)) * 100, 2),
      erro_omissao_pct: lim((1 - pa) * 100, 2),
      F1_pct: lim(f1 * 100, 2),
      especificidade_pct: lim(dividir(VN, VN + FP) * 100, 2),
      acuracia_binaria_pct: lim((VP + VN) / N * 100, 2),
      IoU_pct: lim(dividir(VP, VP + FP + FN) * 100, 2),
      kappa_cond_usuario: lim(dividir(N * VP - ni[j] * nj[j], N * ni[j] - ni[j] * nj[j]), 4),
      kappa_cond_produtor: lim(dividir(N * VP - ni[j] * nj[j], N * nj[j] - ni[j] * nj[j]), 4)
    }));
  }
  var d = qdAd(n);
  var glob = {
    conjunto: rotulo, ano: ANO, n_amostras: N, n_acertos: diag,
    OA_amostral_pct: lim(oa * 100, 2), OA_amostral_IC95_pct: lim(Z * seOAs * 100, 2),
    erro_global_amostral_pct: lim((1 - oa) * 100, 2),
    Kappa_amostral: lim(kappa, 4), Kappa_amostral_LandisKoch: rotuloKappa(kappa),
    UA_media_pct: lim(mediaValidos(UA) * 100, 2), PA_media_pct: lim(mediaValidos(PA) * 100, 2),
    F1_macro_pct: lim(mediaValidos(F1) * 100, 2),
    QD_amostral_pct: lim(d.qd * 100, 2), AD_amostral_pct: lim(d.ad * 100, 2)
  };
  return {porClasse: ee.FeatureCollection(feats), glob: glob, ni: ni, nj: nj, N: N};
}

// Estimadores ajustados por área (Olofsson et al., 2013; 2014)
function estimadoresArea(n, A, cfg) {
  var K = cfg.ids.length, Atot = soma(A), ni = [], p = [], pj = [], U = [], W = [], i, j;
  for (i = 0; i < K; i++) { W[i] = A[i] / Atot; ni[i] = soma(n[i]); }
  for (i = 0; i < K; i++) {
    p[i] = [];
    for (j = 0; j < K; j++) { p[i][j] = ni[i] > 0 ? W[i] * n[i][j] / ni[i] : 0; }
    U[i] = dividir(n[i][i], ni[i]);
  }
  for (j = 0; j < K; j++) { pj[j] = 0; for (i = 0; i < K; i++) { pj[j] += p[i][j]; } }
  var OA = 0, varOA = 0, pe = 0;
  for (i = 0; i < K; i++) {
    OA += p[i][i];
    varOA += dividir(W[i] * W[i] * U[i] * (1 - U[i]), ni[i] - 1);
    pe += W[i] * pj[i];
  }
  var seOA = Math.sqrt(varOA), kappaW = (OA - pe) / (1 - pe);
  var feats = [], PAw = [], F1w = [];
  for (j = 0; j < K; j++) {
    var varPj = 0;
    for (i = 0; i < K; i++) {
      var pij = dividir(n[i][j], ni[i]);
      varPj += dividir(W[i] * W[i] * pij * (1 - pij), ni[i] - 1);
    }
    var Nhat = 0;
    for (i = 0; i < K; i++) { Nhat += dividir(A[i] * n[i][j], ni[i]); }
    var PA = dividir(A[j] * U[j], Nhat);
    var termo1 = dividir(A[j] * A[j] * Math.pow(1 - PA, 2) * U[j] * (1 - U[j]), ni[j] - 1);
    var termo2 = 0;
    for (i = 0; i < K; i++) {
      if (i !== j) { var q = dividir(n[i][j], ni[i]); termo2 += dividir(A[i] * A[i] * q * (1 - q), ni[i] - 1); }
    }
    var icPA = Z * Math.sqrt((termo1 + PA * PA * termo2) / (Nhat * Nhat)) * 100;
    var icUA = Z * Math.sqrt(dividir(U[j] * (1 - U[j]), ni[j] - 1)) * 100;
    var icArea = Z * Atot * Math.sqrt(varPj);
    var F1 = (PA + U[j]) > 0 ? 2 * PA * U[j] / (PA + U[j]) : NaN;
    PAw.push(PA); F1w.push(F1);
    feats.push(ee.Feature(null, {
      ano: ANO, classe_id: cfg.ids[j], classe_nome: cfg.nomes[j],
      n_pontos_mapa: ni[j], peso_Wi: lim(W[j], 6),
      area_mapa_ha: lim(A[j], 2), area_mapa_pct: lim(W[j] * 100, 2),
      area_ajustada_ha: lim(Atot * pj[j], 2), area_ajustada_pct: lim(pj[j] * 100, 2),
      area_ajustada_IC95_ha: lim(icArea, 2),
      area_ajustada_min_ha: lim(Atot * pj[j] - icArea, 2), area_ajustada_max_ha: lim(Atot * pj[j] + icArea, 2),
      diferenca_ajustada_menos_mapa_ha: lim(Atot * pj[j] - A[j], 2),
      UA_pond_pct: lim(U[j] * 100, 2), UA_pond_IC95_pct: lim(icUA, 2),
      erro_comissao_pond_pct: lim((1 - U[j]) * 100, 2),
      PA_pond_pct: lim(PA * 100, 2), PA_pond_IC95_pct: lim(icPA, 2),
      erro_omissao_pond_pct: lim((1 - PA) * 100, 2), F1_pond_pct: lim(F1 * 100, 2)
    }));
  }
  var d = qdAd(p);
  var glob = {
    OA_pond_pct: lim(OA * 100, 2), OA_pond_IC95_pct: lim(Z * seOA * 100, 2),
    OA_pond_min_pct: lim((OA - Z * seOA) * 100, 2), OA_pond_max_pct: lim((OA + Z * seOA) * 100, 2),
    erro_global_pond_pct: lim((1 - OA) * 100, 2),
    Kappa_pond: lim(kappaW, 4), Kappa_pond_LandisKoch: rotuloKappa(kappaW),
    UA_media_pond_pct: lim(mediaValidos(U) * 100, 2), PA_media_pond_pct: lim(mediaValidos(PAw) * 100, 2),
    F1_macro_pond_pct: lim(mediaValidos(F1w) * 100, 2),
    QD_pond_pct: lim(d.qd * 100, 2), AD_pond_pct: lim(d.ad * 100, 2), area_total_ha: lim(Atot, 2)
  };
  return {porClasse: ee.FeatureCollection(feats), glob: glob, p: p, OA: OA, seOA: seOA, kappa: kappaW, U: U, PA: PAw};
}

function featuresMatriz(m, digitos, cfg, tabela) {
  var K = cfg.ids.length, feats = [], colTot = [], geral = 0, i, j;
  for (j = 0; j < K; j++) { colTot[j] = 0; }
  for (i = 0; i < K; i++) {
    var d = {tabela: tabela, classe_mapa_id: cfg.ids[i], classe_mapa_nome: cfg.nomes[i]}, tl = 0;
    for (j = 0; j < K; j++) { d['ref_' + cfg.ids[j]] = lim(m[i][j], digitos); tl += m[i][j]; colTot[j] += m[i][j]; }
    d.total = lim(tl, digitos); geral += tl;
    feats.push(ee.Feature(null, d));
  }
  var dt = {tabela: tabela, classe_mapa_id: -1, classe_mapa_nome: 'Total referência'};
  for (j = 0; j < K; j++) { dt['ref_' + cfg.ids[j]] = lim(colTot[j], digitos); }
  dt.total = lim(geral, digitos);
  feats.push(ee.Feature(null, dt));
  return ee.FeatureCollection(feats);
}
function colsMatriz(cfg) {
  return ['tabela', 'classe_mapa_id', 'classe_mapa_nome']
    .concat(cfg.ids.map(function(i) { return 'ref_' + i; }), ['total']);
}

function avaliarCriterios(aj, cfg) {
  var oa = aj.OA * 100, ic = Z * aj.seOA * 100, t, baixas = [];
  print('--- ' + cfg.rotulo + ': AVALIAÇÃO FRENTE AOS CRITÉRIOS DE REFERÊNCIA ---');
  print('Acurácia global ponderada: ' + oa.toFixed(2) + '% (IC95%: ' + (oa - ic).toFixed(2) + ' a ' +
        (oa + ic).toFixed(2) + '%). Meta >= ' + LIM_OA + '%: ' +
        (oa >= LIM_OA ? (oa - ic >= LIM_OA ? 'ATENDE, inclusive o limite inferior do IC.'
                                           : 'estimativa pontual ATENDE, mas o limite inferior do IC não.')
                      : 'NÃO ATENDE.'));
  print('Kappa ponderado: ' + aj.kappa.toFixed(3) + ' (' + rotuloKappa(aj.kappa) + '). Meta >= ' + LIM_KAPPA +
        ': ' + (aj.kappa >= LIM_KAPPA ? 'ATENDE.' : 'NÃO ATENDE.'));
  for (t = 0; t < cfg.ids.length; t++) {
    if (aj.U[t] * 100 < LIM_CLASSE) { baixas.push(cfg.nomes[t] + ' (UA ' + (aj.U[t] * 100).toFixed(1) + '%)'); }
    if (aj.PA[t] * 100 < LIM_CLASSE) { baixas.push(cfg.nomes[t] + ' (PA ' + (aj.PA[t] * 100).toFixed(1) + '%)'); }
  }
  print('Classes com UA ou PA abaixo de ' + LIM_CLASSE + '%: ' + (baixas.length ? baixas.join('; ') : 'nenhuma'));
}

// Colunas dos CSVs
var COLS_CLASSE_AMOSTRAL = ['conjunto', 'ano', 'classe_id', 'classe_nome', 'n_mapa', 'n_referencia',
  'VP', 'FP', 'FN', 'VN', 'UA_pct', 'UA_IC95_pct', 'erro_comissao_pct', 'PA_pct', 'PA_IC95_pct',
  'erro_omissao_pct', 'F1_pct', 'especificidade_pct', 'acuracia_binaria_pct', 'IoU_pct',
  'kappa_cond_usuario', 'kappa_cond_produtor'];
var COLS_GLOBAL_AMOSTRAL = ['conjunto', 'ano', 'n_amostras', 'n_acertos', 'OA_amostral_pct', 'OA_amostral_IC95_pct',
  'erro_global_amostral_pct', 'Kappa_amostral', 'Kappa_amostral_LandisKoch', 'UA_media_pct', 'PA_media_pct',
  'F1_macro_pct', 'QD_amostral_pct', 'AD_amostral_pct'];
var COLS_CLASSE_AJUSTADA = ['ano', 'classe_id', 'classe_nome', 'n_pontos_mapa', 'peso_Wi', 'area_mapa_ha',
  'area_mapa_pct', 'area_ajustada_ha', 'area_ajustada_pct', 'area_ajustada_IC95_ha', 'area_ajustada_min_ha',
  'area_ajustada_max_ha', 'diferenca_ajustada_menos_mapa_ha', 'UA_pond_pct', 'UA_pond_IC95_pct',
  'erro_comissao_pond_pct', 'PA_pond_pct', 'PA_pond_IC95_pct', 'erro_omissao_pond_pct', 'F1_pond_pct'];
var COLS_GLOBAL_POND = ['OA_pond_pct', 'OA_pond_IC95_pct', 'OA_pond_min_pct', 'OA_pond_max_pct',
  'erro_global_pond_pct', 'Kappa_pond', 'Kappa_pond_LandisKoch', 'UA_media_pond_pct', 'PA_media_pond_pct',
  'F1_macro_pond_pct', 'QD_pond_pct', 'AD_pond_pct', 'area_total_ha'];

// ============================
// 3 - FUNÇÕES DO GEE
// ============================
function exportarCSV(fc, nome, colunas) {
  Export.table.toDrive({collection: fc, description: nome + '_' + DESC, folder: PASTA,
                        fileFormat: 'CSV', selectors: colunas});
}

// Converte a coluna de referência para inteiro (o upload de CSV pode gravar texto)
function normalizarRef(fc, col) {
  return fc.filter(ee.Filter.notNull([col])).filter(ee.Filter.neq(col, '')).map(function(f) {
    var v = f.get(col);
    var num = ee.Number(ee.Algorithms.If(ee.Algorithms.ObjectType(v).equals('String'),
                                         ee.Number.parse(ee.String(v)), v));
    return f.set(col, num.int());
  });
}

function detectarColuna(colunas, regex, excluir) {
  for (var i = 0; i < colunas.length; i++) {
    if (regex.test(colunas[i]) && excluir.indexOf(colunas[i]) < 0) { return colunas[i]; }
  }
  return null;
}

// ============================
// 4 - VALIDAÇÃO DE UM PRODUTO
// ============================
function validarProduto(mapa, cfg) {
  var P = cfg.rotulo;
  print('================ VALIDAÇÃO: ' + P + ' ================');
  var refBruto = ee.FeatureCollection(cfg.asset);
  print('Pontos lidos de:', cfg.asset);
  var colunas = refBruto.first().propertyNames().getInfo();
  print('Colunas do asset:', colunas);
  if (colunas.indexOf(cfg.colRef) < 0) {
    print('ERRO: o asset não tem a coluna \'' + cfg.colRef + '\'. Corrija o nome e rode de novo.');
    return null;
  }
  var obrig = [cfg.colRef, 'id', 'lon', 'lat', 'system:index'];
  var colFonte = COL_FONTE || detectarColuna(colunas, /fonte|source|imagem|sensor|satelite/i, obrig);
  var colData = COL_DATA || detectarColuna(colunas, /data|date/i, obrig.concat([colFonte]));
  print('Coluna de fonte detectada:', colFonte, 'Coluna de data detectada:', colData);
  var extras = ['id'].concat(colFonte ? [colFonte] : [], colData ? [colData] : [])
                     .filter(function(c) { return colunas.indexOf(c) > -1; });

  var mapaR = mapa.rename('mapa');

  // ---- 4.1 Consistência: o mapa deve reproduzir a estratificação do sorteio
  var hist = mapaR.sampleRegions({collection: refBruto, properties: [], scale: ESCALA, tileScale: 4})
                  .aggregate_histogram('mapa').getInfo() || {};
  var ok = cfg.idsSorteio.every(function(c, i) { return (hist[String(c)] || 0) === cfg.nPontos[i]; });
  print('Pontos por classe do MAPA (esperado ' + cfg.nPontos.join('/') + '):', hist);
  print(ok ? 'CONSISTÊNCIA OK: o mapa lido é o que gerou os pontos.'
           : 'ATENÇÃO: o mapa NÃO reproduz a estratificação dos pontos. Confira ASSET_MAPA e o asset de pontos ' +
             'antes de usar estas estimativas.');

  // ---- 4.2 Pontos válidos, agrupamento (se houver) e pares referência x mapa
  var ref = normalizarRef(refBruto, cfg.colRef);
  var refValidos = ref.filter(ee.Filter.inList(cfg.colRef, cfg.idsSorteio));
  if (cfg.remap) {
    var de = ee.List(cfg.remap.de), para = ee.List(cfg.remap.para);
    refValidos = refValidos.map(function(f) {
      return f.set(cfg.colRef, para.get(de.indexOf(f.get(cfg.colRef))));
    });
    mapaR = mapaR.remap(cfg.remap.de, cfg.remap.para).rename('mapa');
    print('AGRUPAMENTO aplicado no mapa e na referência: ' + cfg.remap.de.join(',') + ' -> ' +
          cfg.remap.para.join(','));
  }
  var nTot = refBruto.size().getInfo(), nVal = refValidos.size().getInfo();
  print('Pontos no asset: ' + nTot + ' | com referência válida: ' + nVal +
        ' | descartados (vazios ou fora dos códigos): ' + (nTot - nVal));
  print('Pontos por classe de REFERÊNCIA:', refValidos.aggregate_histogram(cfg.colRef));

  var pares = mapaR.sampleRegions({collection: refValidos, properties: [cfg.colRef].concat(extras),
                                   scale: ESCALA, tileScale: 4, geometries: true})
    .map(function(f) {
      var c = f.geometry().coordinates();
      return f.set({acerto: ee.Number(f.get(cfg.colRef)).eq(ee.Number(f.get('mapa'))),
                    lon: c.get(0), lat: c.get(1)});
    });
  var colsPares = extras.concat([cfg.colRef, 'mapa', 'acerto', 'lon', 'lat']);
  exportarCSV(pares, P + '_T9_Pares_referencia_mapa', colsPares);
  Export.table.toDrive({collection: pares, description: P + '_T9_Pares_SHP_' + DESC, folder: PASTA,
                        fileFormat: 'SHP', selectors: colsPares});
  Map.addLayer(pares.filter(ee.Filter.eq('acerto', 0)), {color: 'FF00FF'}, P + ' - pontos com erro', false);
  Map.addLayer(pares.filter(ee.Filter.eq('acerto', 1)), {color: '00FFFF'}, P + ' - pontos com acerto', false);

  // ---- 4.3 Matriz de confusão e áreas mapeadas
  var n = transpor(pares.errorMatrix(cfg.colRef, 'mapa', cfg.ids).array().getInfo());
  var grupos = ee.Image.pixelArea().divide(10000).addBands(mapaR).reduceRegion({
    reducer: ee.Reducer.sum().group({groupField: 1, groupName: 'classe'}),
    geometry: aoi, crs: CRS, scale: ESCALA, maxPixels: 1e13, tileScale: 16
  }).get('groups').getInfo();
  var A = cfg.ids.map(function() { return 0; });
  grupos.forEach(function(g) { var p = cfg.ids.indexOf(g.classe); if (p > -1) { A[p] = g.sum; } });
  print('Área mapeada por classe (ha):', A, 'Área total (ha):', soma(A));

  // ---- 4.4 Métricas
  var am = metricasAmostrais(n, P + '_pontos_independentes', cfg);
  var aj = estimadoresArea(n, A, cfg);
  var glob = am.glob, ch;
  for (ch in aj.glob) { if (aj.glob.hasOwnProperty(ch)) { glob[ch] = aj.glob[ch]; } }
  var fcGlobal = ee.FeatureCollection([ee.Feature(null, glob)]);

  var t1 = featuresMatriz(n, 0, cfg, 'T1_contagens');
  var t2 = featuresMatriz(matrizPct(n, true), 2, cfg, 'T2_pct_linha_usuario');
  var t3 = featuresMatriz(matrizPct(n, false), 2, cfg, 'T3_pct_coluna_produtor');
  var t4 = featuresMatriz(aj.p, 6, cfg, 'T4_proporcoes_area');

  print('T1 - Matriz de confusão amostral (linhas = mapa, colunas = referência):', t1);
  print('T2 - Matriz em % por linha (acurácia do usuário):', t2);
  print('T3 - Matriz em % por coluna (acurácia do produtor):', t3);
  print('T4 - Matriz de proporções de área estimadas (Olofsson et al., 2014):', t4);
  print('T5 - Métricas por classe (amostrais):', am.porClasse);
  print('T6 - Métricas por classe ajustadas por área e áreas ajustadas (IC 95%):', aj.porClasse);
  print('T7 - Métricas globais:', fcGlobal);
  avaliarCriterios(aj, cfg);

  exportarCSV(t1, P + '_T1_Matriz_confusao_amostral', colsMatriz(cfg));
  exportarCSV(t2, P + '_T2_Matriz_pct_linha', colsMatriz(cfg));
  exportarCSV(t3, P + '_T3_Matriz_pct_coluna', colsMatriz(cfg));
  exportarCSV(t4, P + '_T4_Matriz_proporcoes_area', colsMatriz(cfg));
  exportarCSV(am.porClasse, P + '_T5_Metricas_classe_amostrais', COLS_CLASSE_AMOSTRAL);
  exportarCSV(aj.porClasse, P + '_T6_Metricas_classe_ajustadas_areas', COLS_CLASSE_AJUSTADA);
  exportarCSV(fcGlobal, P + '_T7_Metricas_globais', COLS_GLOBAL_AMOSTRAL.concat(COLS_GLOBAL_POND));

  // ---- 4.5 T8: acurácia por fonte e por data da imagem de referência
  var linhasT8 = [];
  [colFonte, colData].forEach(function(col) {
    if (!col) { return; }
    pares.aggregate_array(col).distinct().getInfo().forEach(function(valor) {
      var sub = pares.filter(ee.Filter.eq(col, valor));
      var nS = sub.size().getInfo();
      var acS = sub.aggregate_sum('acerto').getInfo();
      var oaS = nS > 0 ? acS / nS : NaN;
      linhasT8.push(ee.Feature(null, {
        conjunto: P, agrupamento: col, valor: String(valor), n_pontos: nS, n_acertos: acS,
        OA_amostral_pct: lim(oaS * 100, 2),
        OA_IC95_pct: lim(Z * Math.sqrt(dividir(oaS * (1 - oaS), nS - 1)) * 100, 2)
      }));
    });
  });
  if (linhasT8.length) {
    var t8 = ee.FeatureCollection(linhasT8);
    print('T8 - Acurácia amostral por fonte/data da referência (sensibilidade):', t8);
    exportarCSV(t8, P + '_T8_Acuracia_por_fonte_data',
                ['conjunto', 'agrupamento', 'valor', 'n_pontos', 'n_acertos', 'OA_amostral_pct', 'OA_IC95_pct']);
  } else {
    print('T8 não gerada: nenhuma coluna de fonte/data encontrada. Defina COL_FONTE e COL_DATA.');
  }
  return aj;
}

// ============================
// 5 - EXECUÇÃO
// ============================
print('==== PARTE 3 - VALIDAR ' + DESC + ' ====');
print('Data de execução:', new Date().toISOString());
var mapa = ee.Image(ASSET_MAPA);
print('Mapa lido de:', ASSET_MAPA, mapa.bandNames());

if (VALIDAR_LULC) {
  Map.addLayer(mapa.select('classification'), {min: 1, max: 5, palette: PALETA}, 'LULC 2025 - 5 classes (asset)', false);
  if (AGRUPAR) {
    var mapa4 = mapa.select('classification').remap(REMAP_DE, REMAP_PARA).rename('classification').toByte();
    Map.addLayer(mapa4, {min: 1, max: 5, palette: ['006400', 'C8B560', '0000FF', 'C8B560', 'FF0000']},
                 'LULC 2025 - 4 classes (agrupado)');
    // GeoTIFF do mapa agrupado para os layouts no QGIS (códigos 1, 2, 3 e 5)
    Export.image.toDrive({image: mapa4, description: 'LULC_4classes_' + DESC, folder: PASTA,
                          crs: CRS, scale: ESCALA, region: aoi, maxPixels: 1e13});
  }
  validarProduto(mapa.select(CFG_LULC.banda), CFG_LULC);
}
if (VALIDAR_NDBI) {
  Map.addLayer(mapa.select('NDBI_bin').selfMask(), {palette: ['FF0000']}, 'NDBI binário 2025 (asset)', false);
  validarProduto(mapa.select(CFG_NDBI.banda), CFG_NDBI);
}

// ====================================================================
// NOTAS PARA O TEXTO
// - OA, UA, PA e áreas ajustadas: estimadores estratificados de Olofsson et al.
//   (2013; 2014), com IC 95%. Kappa reportado só por comparabilidade
//   (Pontius e Millones, 2011; Foody, 2020); QD e AD: Pontius e Millones (2011).
// - Critérios LIM_OA (Anderson et al., 1976), LIM_CLASSE (Thomlinson et al., 1999)
//   e escala do Kappa (Landis e Koch, 1977) são referências usuais, não normas.
// - Agrupamento Veg. Rasteira + Solo Exposto: justificado pela confusão
//   espectral entre as duas classes na estação seca (matriz T1 com 5 classes).
// - T9 em SHP permite mapear os pontos com erro e mostrar se eles se concentram
//   em áreas de transição (bordas entre classes, pixels mistos).
// ====================================================================
