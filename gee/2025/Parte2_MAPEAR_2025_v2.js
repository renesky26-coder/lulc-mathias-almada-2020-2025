// ====================================================================
// LULC + NDBI - BACIA DO RIO MATHIAS ALMADA | ANO 2025
// PARTE 2 - MAPEAR: CLASSIFICAÇÃO (RANDOM FOREST), NDBI CALIBRADO E PONTOS
//
// Imports necessários (nomes exatos):
//   table          -> limite da bacia (projects/SEU-PROJETO-GEE/assets/BH_Rio_Almada)
//   vegDensa, vegRasteira, agua, soloExposto, areaUrbana -> polígonos de treino
//
// FLUXO
//  1) MAPEAR (este script): lê o mosaico FIXO de 2025, treina o RF, faz validação
//     cruzada por polígono, calibra o limiar do NDBI com as amostras, calcula
//     áreas, sorteia os pontos de validação (LULC e NDBI) e exporta tudo.
//  2) Manual: interpretar os pontos ÀS CEGAS (Google Earth Pro, imagens de 2025)
//     e subir os CSVs como assets:
//       Pontos_Validacao_LULC_MathiasAlmada_2025      (id, lon, lat, ref_classe 1-5)
//       Pontos_Validacao_NDBI_MathiasAlmada_2025 (id, lon, lat, ref_construido 0/1)
//     Colunas opcionais: ref_date, ref_fonte, ref_cena.
//  3) A etapa VALIDAR (Olofsson et al., 2014) será acrescentada depois que
//     os pontos estiverem rotulados.
// ====================================================================

// ============================
// 1 - PARÂMETROS
// ============================
var ANO = 2025;

var AREA = 'MathiasAlmada';
var DESC = AREA + '_' + ANO;
var PASTA = 'LULC_' + DESC;
var ASSET_BASE = 'projects/SEU-PROJETO-GEE/assets/';   // <- troque pelo seu projeto do Earth Engine
var ASSET_MOSAICO = ASSET_BASE + 'Mosaico_' + DESC;      // gerado na Parte 1

// CENAS FIXAS DE 2025. O mosaico é lido do asset da Parte 1 (congelado).
// Preencha DATAS_FIXAS com a coluna 'data' do CSV Cenas_S2_MathiasAlmada_2025
// (só é usada se o asset do mosaico não existir).
var TILE = '21JYM';
var DATAS_FIXAS = [];   // ex.: ['2025-06-08', '2025-06-18', ...]
var CS_LIMIAR = 0.60;
var MIN_OBS = 1;

// Classificação e validação interna
var PIXELS_POR_POLIGONO = 100;
var NUM_ARVORES = 100;
var K_FOLDS = 5;

// Validação independente
var GERAR_PONTOS = true;   // true AGORA (mapa v2). Mude para false só depois de exportar os pontos do mapa final
// Pontos por classe do MAPA LULC: [Veg Densa, Veg Rasteira, Água, Solo, Urbana].
// Água tem área muito pequena (lagos pequenos + rio Paraná na foz): 20 pontos.
var N_PONTOS = [50, 50, 20, 50, 50];
var N_PONTOS_NDBI = [50, 50];                // 0 = não construído, 1 = construído

// NDBI
// null = limiar calibrado com as amostras deste ano (curva TPR x FPR, índice J).
// Em 2025, informe aqui o limiar obtido em 2020 para a comparação ser coerente.
var LIMIAR_NDBI_FIXO = -0.03;   // LIMIAR CALIBRADO EM 2020 (não alterar)
var CRITERIO_LIMIAR = 'J_medio';  // 'J_medio' (urbana x média das outras classes)
                                  // ou 'J_solo' (urbana x solo exposto)
var LIMIAR_MNDWI = 0;             // água: MNDWI > 0 (Xu, 2006)
var PRODUTO_NDBI = 'refinado';    // 'calibrado' ou 'refinado' (vai para o asset e é validado)

// Gerais
var SEED = 42;
var CRS = 'EPSG:32721';
var ESCALA = 10;
var PROJ = ee.Projection(CRS).atScale(ESCALA);

var ASSET_SUFIXO = '_v2';         // VERSÃO 2 (amostras revisadas). Se refizer de novo: '_v3'
var ASSET_MAPA = ASSET_BASE + 'LULC_' + DESC + ASSET_SUFIXO;

var CFG_LULC = {
  ids: [1, 2, 3, 4, 5],
  nomes: ['Vegetação Densa', 'Vegetação Rasteira', 'Água', 'Solo Exposto', 'Área Urbana']
};
var CFG_NDBI = {ids: [0, 1], nomes: ['Não construído', 'Construído/impermeável']};
var PALETA = ['006400', 'ADFF2F', '0000FF', 'D2691E', 'FF0000'];
var CLASSE_URBANA = 5;
var CLASSE_SOLO = 4;

var bandas_S2 = ['B2', 'B3', 'B4', 'B8', 'B11', 'B12'];
var bandasPrevisoras = bandas_S2.concat(['NDVI', 'MNDWI']);

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

function metricasAmostrais(n, rotulo, cfg) {
  var K = cfg.ids.length, ni = [], nj = [], N = 0, i, j;
  for (i = 0; i < K; i++) { ni[i] = soma(n[i]); N += ni[i]; }
  for (j = 0; j < K; j++) { nj[j] = 0; for (i = 0; i < K; i++) { nj[j] += n[i][j]; } }
  var diag = 0, pe = 0;
  for (i = 0; i < K; i++) { diag += n[i][i]; pe += ni[i] * nj[i]; }
  var oa = diag / N;
  var kappa = (oa - pe / (N * N)) / (1 - pe / (N * N));
  var UA = [], PA = [], F1 = [], feats = [];
  for (j = 0; j < K; j++) {
    var VP = n[j][j], FP = ni[j] - VP, FN = nj[j] - VP, VN = N - VP - FP - FN;
    var ua = dividir(VP, ni[j]), pa = dividir(VP, nj[j]);
    var f1 = (ua + pa) > 0 ? 2 * ua * pa / (ua + pa) : NaN;
    UA.push(ua); PA.push(pa); F1.push(f1);
    feats.push(ee.Feature(null, {
      conjunto: rotulo, ano: ANO, classe_id: cfg.ids[j], classe_nome: cfg.nomes[j],
      n_mapa: ni[j], n_referencia: nj[j], VP: VP, FP: FP, FN: FN, VN: VN,
      UA_pct: lim(ua * 100, 2), erro_comissao_pct: lim((1 - ua) * 100, 2),
      PA_pct: lim(pa * 100, 2), erro_omissao_pct: lim((1 - pa) * 100, 2),
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
    conjunto: rotulo, ano: ANO, n_amostras: N,
    OA_amostral_pct: lim(oa * 100, 2), erro_global_amostral_pct: lim((1 - oa) * 100, 2),
    Kappa_amostral: lim(kappa, 4), Kappa_amostral_LandisKoch: rotuloKappa(kappa),
    UA_media_pct: lim(mediaValidos(UA) * 100, 2), PA_media_pct: lim(mediaValidos(PA) * 100, 2),
    F1_macro_pct: lim(mediaValidos(F1) * 100, 2),
    QD_amostral_pct: lim(d.qd * 100, 2), AD_amostral_pct: lim(d.ad * 100, 2)
  };
  return {porClasse: ee.FeatureCollection(feats), glob: glob, ni: ni, nj: nj, N: N};
}

function featuresMatriz(m, digitos, cfg) {
  var K = cfg.ids.length, feats = [], colTot = [], geral = 0, i, j;
  for (j = 0; j < K; j++) { colTot[j] = 0; }
  for (i = 0; i < K; i++) {
    var d = {classe_mapa_id: cfg.ids[i], classe_mapa_nome: cfg.nomes[i]}, tl = 0;
    for (j = 0; j < K; j++) { d['ref_' + cfg.ids[j]] = lim(m[i][j], digitos); tl += m[i][j]; colTot[j] += m[i][j]; }
    d.total = lim(tl, digitos); geral += tl;
    feats.push(ee.Feature(null, d));
  }
  var dt = {classe_mapa_id: -1, classe_mapa_nome: 'Total referência'};
  for (j = 0; j < K; j++) { dt['ref_' + cfg.ids[j]] = lim(colTot[j], digitos); }
  dt.total = lim(geral, digitos);
  feats.push(ee.Feature(null, dt));
  return ee.FeatureCollection(feats);
}

// Colunas dos CSVs
function colsMatriz(cfg) {
  return ['classe_mapa_id', 'classe_mapa_nome'].concat(cfg.ids.map(function(i) { return 'ref_' + i; }), ['total']);
}
var COLS_CLASSE_AMOSTRAL = ['conjunto', 'ano', 'classe_id', 'classe_nome', 'n_mapa', 'n_referencia',
  'VP', 'FP', 'FN', 'VN', 'UA_pct', 'erro_comissao_pct', 'PA_pct', 'erro_omissao_pct', 'F1_pct',
  'especificidade_pct', 'acuracia_binaria_pct', 'IoU_pct', 'kappa_cond_usuario', 'kappa_cond_produtor'];
var COLS_GLOBAL_AMOSTRAL = ['conjunto', 'ano', 'n_amostras', 'OA_amostral_pct', 'erro_global_amostral_pct',
  'Kappa_amostral', 'Kappa_amostral_LandisKoch', 'UA_media_pct', 'PA_media_pct', 'F1_macro_pct',
  'QD_amostral_pct', 'AD_amostral_pct'];
// ============================
// 3 - FUNÇÕES DO GEE
// ============================
function mascarar(image) {
  var scl = image.select('SCL');
  var sclRuim = scl.eq(0).or(scl.eq(1)).or(scl.eq(3)).or(scl.eq(8)).or(scl.eq(9)).or(scl.eq(10));
  var limpo = sclRuim.not().and(image.select('cs_cdf').gte(CS_LIMIAR));
  return image.updateMask(limpo).select(bandas_S2).divide(10000)
              .copyProperties(image, ['system:time_start']);
}
function addIndices(image) {
  return image.addBands([
    image.normalizedDifference(['B8', 'B4']).rename('NDVI'),
    image.normalizedDifference(['B3', 'B11']).rename('MNDWI'),
    image.normalizedDifference(['B11', 'B8']).rename('NDBI')
  ]);
}

// Mosaico: asset da Parte 1 (preferencial) ou reconstrução pelas datas fixas
function obterMosaico() {
  var info = null;
  try { info = ee.data.getAsset(ASSET_MOSAICO); } catch (e) { info = null; }
  if (info) {
    print('Mosaico lido do asset congelado:', ASSET_MOSAICO);
    return ee.Image(ASSET_MOSAICO);
  }
  if (DATAS_FIXAS.length === 0) {
    throw new Error('Asset ' + ASSET_MOSAICO + ' não encontrado e DATAS_FIXAS vazia. ' +
                    'Rode a Parte 1 e execute a tarefa Asset_Mosaico_' + DESC + ' antes.');
  }
  print('ATENÇÃO: asset do mosaico não encontrado. Reconstruindo com as ' + DATAS_FIXAS.length + ' datas fixas.');
  var col = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
    .filterBounds(aoi).filterDate(ANO + '-01-01', (ANO + 1) + '-01-01')
    .filter(ee.Filter.eq('MGRS_TILE', TILE))
    .map(function(i) { return i.set('dia', i.date().format('YYYY-MM-dd')); })
    .filter(ee.Filter.inList('dia', DATAS_FIXAS));
  print('Cenas encontradas (esperado ' + DATAS_FIXAS.length + '):', col.size(), col.aggregate_array('system:index'));
  var colM = col.linkCollection(ee.ImageCollection('GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED'), ['cs_cdf']).map(mascarar);
  var nObs = colM.select('B4').count().unmask(0).clip(aoi).rename('n_obs');
  return addIndices(colM.median()).clip(aoi).updateMask(nObs.gte(MIN_OBS)).addBands(nObs);
}

function atribuirFolds(fc, nFolds, seed) {
  var ord = fc.randomColumn('rnd', seed).sort('rnd');
  var n = ord.size(), lista = ord.toList(n);
  return ee.FeatureCollection(ee.List.sequence(0, n.subtract(1)).map(function(i) {
    return ee.Feature(lista.get(i)).set('fold', ee.Number(i).mod(nFolds));
  }));
}
function extrairPixels(fcPol, img) {
  return fcPol.map(function(f) {
    return img.sample({region: f.geometry(), projection: PROJ, numPixels: PIXELS_POR_POLIGONO,
                       seed: SEED, tileScale: 16})
      .map(function(p) { return p.set({'class': f.get('class'), 'poly_id': f.get('poly_id'), 'fold': f.get('fold')}); });
  }).flatten();
}
function novoRF() { return ee.Classifier.smileRandomForest({numberOfTrees: NUM_ARVORES, seed: SEED}); }

function exportarCSV(fc, nome, colunas) {
  Export.table.toDrive({collection: fc, description: nome + '_' + DESC, folder: PASTA,
                        fileFormat: 'CSV', selectors: colunas});
}
function exportarImagem(img, nome) {
  Export.image.toDrive({image: img, description: nome + '_' + DESC, folder: PASTA,
                        crs: CRS, scale: ESCALA, region: aoi, maxPixels: 1e13});
}

// Área (ha e %) por classe de uma imagem categórica
function areaPorClasse(img, produto, nomesDic) {
  var areaTot = ee.Number(ee.Image.pixelArea().divide(10000).updateMask(img.mask()).reduceRegion({
    reducer: ee.Reducer.sum(), geometry: aoi, crs: CRS, scale: ESCALA, maxPixels: 1e13, tileScale: 16
  }).get('area'));
  var grupos = ee.Image.pixelArea().divide(10000).addBands(img.toInt()).reduceRegion({
    reducer: ee.Reducer.sum().group({groupField: 1, groupName: 'classe'}),
    geometry: aoi, crs: CRS, scale: ESCALA, maxPixels: 1e13, tileScale: 16
  }).get('groups');
  return ee.FeatureCollection(ee.List(grupos).map(function(g) {
    g = ee.Dictionary(g);
    var c = ee.Number(g.get('classe')).int(), a = ee.Number(g.get('sum'));
    return ee.Feature(null, {ano: ANO, produto: produto, classe: c,
      classe_nome: ee.Dictionary(nomesDic).get(c.format()),
      area_ha: a, area_pct: a.divide(areaTot).multiply(100)});
  }));
}
var COLS_AREA = ['ano', 'produto', 'classe', 'classe_nome', 'area_ha', 'area_pct'];

// Calibração do limiar do NDBI com as amostras de treino:
// para cada limiar t, TPR = fração dos pixels de Área Urbana com NDBI > t;
// FPR_k = fração dos pixels da classe k com NDBI > t; J = TPR - FPR (Youden, 1950).
function curvaLimiares(px) {
  var urb = px.filter(ee.Filter.eq('class', CLASSE_URBANA));
  var nUrb = urb.size();
  var outras = [1, 2, 3, 4];
  return ee.FeatureCollection(ee.List.sequence(-0.40, 0.40, 0.01).map(function(t) {
    t = ee.Number(t).multiply(1000).round().divide(1000);
    var tpr = urb.filter(ee.Filter.gt('NDBI', t)).size().divide(nUrb);
    var fprs = ee.List(outras.map(function(c) {
      var cl = px.filter(ee.Filter.eq('class', c));
      return cl.filter(ee.Filter.gt('NDBI', t)).size().divide(cl.size());
    }));
    var fprMedio = ee.Number(fprs.reduce(ee.Reducer.mean()));
    return ee.Feature(null, {
      limiar: t, TPR_urbana: tpr,
      FPR_vegDensa: fprs.get(0), FPR_vegRasteira: fprs.get(1), FPR_agua: fprs.get(2), FPR_soloExposto: fprs.get(3),
      FPR_medio: fprMedio, J_medio: tpr.subtract(fprMedio), J_solo: tpr.subtract(ee.Number(fprs.get(3)))
    });
  }));
}
var COLS_CURVA = ['limiar', 'TPR_urbana', 'FPR_vegDensa', 'FPR_vegRasteira', 'FPR_agua', 'FPR_soloExposto',
                  'FPR_medio', 'J_medio', 'J_solo'];

// Pontos estratificados, exportados SEM a classe do mapa (interpretação às cegas)
function gerarPontos(img, banda, ids, nPorClasse, nome) {
  var brutos = img.select(banda).stratifiedSample({
    numPoints: 0, classBand: banda, region: aoi, projection: PROJ, seed: SEED,
    classValues: ids, classPoints: nPorClasse, dropNulls: true, tileScale: 16, geometries: true
  });
  print(nome + ' - pontos gerados por classe do mapa (compare com ' + nPorClasse.join('/') + '):',
        brutos.aggregate_histogram(banda));
  var nPts = brutos.size();
  var lista = brutos.randomColumn('r', SEED).sort('r').toList(nPts);
  var pts = ee.FeatureCollection(ee.List.sequence(0, nPts.subtract(1)).map(function(i) {
    var g = ee.Feature(lista.get(i)).geometry(), c = g.coordinates();
    return ee.Feature(g, {id: ee.Number(i).add(1), lon: c.get(0), lat: c.get(1)});
  }));
  exportarCSV(pts, nome, ['id', 'lon', 'lat']);
  Export.table.toDrive({collection: pts, description: nome + '_KML_' + DESC, folder: PASTA,
                        fileFormat: 'KML', selectors: ['id']});   // abre direto no Google Earth Pro
  return pts;
}

// ============================
// 4 - ETAPA 'MAPEAR'
// ============================
function etapaMapear() {
  print('==== PARTE 2 - MAPEAR ' + DESC + ' ====');
  print('Data de execução:', new Date().toISOString());
  print('VERSÃO DO MAPA:', ASSET_SUFIXO || '(original)', '| asset de saída:', ASSET_MAPA);
  var mosaico = obterMosaico();
  print('Bandas do mosaico:', mosaico.bandNames());
  var ndvi = mosaico.select('NDVI'), mndwi = mosaico.select('MNDWI'), ndbi = mosaico.select('NDBI');

  Map.addLayer(mosaico, {bands: ['B4', 'B3', 'B2'], min: 0, max: 0.3, gamma: 1.4}, '1. RGB 2025');
  Map.addLayer(mosaico, {bands: ['B12', 'B8', 'B4'], min: 0, max: 0.4}, '2. Falsa cor SWIR', false);

  // ---- 4.1 Polígonos de treino
  var colecoesClasse = [vegDensa, vegRasteira, agua, soloExposto, areaUrbana];
  var poligonos = ee.FeatureCollection([]);
  colecoesClasse.forEach(function(fc, i) {
    var id = CFG_LULC.ids[i];
    var rotulados = ee.FeatureCollection(fc).map(function(f) {
      return f.set({'class': id, 'poly_id': ee.String('c' + id + '_').cat(ee.String(f.get('system:index')))});
    });
    poligonos = poligonos.merge(atribuirFolds(rotulados, K_FOLDS, SEED));
  });
  print('Polígonos de treino por classe:', poligonos.aggregate_histogram('class'));
  print('Área dos polígonos de treino por classe (ha):', ee.Dictionary.fromLists(
    CFG_LULC.ids.map(String),
    CFG_LULC.ids.map(function(c) {
      return poligonos.filter(ee.Filter.eq('class', c)).geometry(1).area(1).divide(10000);
    })));

  // ---- 4.2 Pixels de treino (previsoras + NDBI, este só para calibrar o limiar)
  var imgAmostra = mosaico.select(bandasPrevisoras.concat(['NDBI']));
  var pixels = extrairPixels(poligonos, imgAmostra);
  print('Pixels de treino por classe:', pixels.aggregate_histogram('class'));
  print('Pixels por fold:', pixels.aggregate_histogram('fold'));

  // ---- 4.3 Random Forest e mapa
  var classificador = novoRF().train({features: pixels, classProperty: 'class', inputProperties: bandasPrevisoras});
  var classificado = mosaico.select(bandasPrevisoras).classify(classificador).rename('classification');
  print('Importância das variáveis (RF):', ee.Dictionary(classificador.explain()).get('importance'));
  Map.addLayer(classificado, {min: 1, max: 5, palette: PALETA}, '3. LULC 2025 (RF)');

  // ---- 4.4 Validação cruzada por polígono (estimativa interna, complementar)
  var matrizesCV = [];
  for (var k = 0; k < K_FOLDS; k++) {
    var rfK = novoRF().train({features: pixels.filter(ee.Filter.neq('fold', k)),
                              classProperty: 'class', inputProperties: bandasPrevisoras});
    matrizesCV.push(pixels.filter(ee.Filter.eq('fold', k)).classify(rfK)
      .errorMatrix('class', 'classification', CFG_LULC.ids).array());
  }
  var nCV = transpor(matrizesCV.reduce(function(a, b) { return a.add(b); }).getInfo());
  var resCV = metricasAmostrais(nCV, 'CV_poligono_' + K_FOLDS + 'folds', CFG_LULC);
  var globalCV = ee.FeatureCollection([ee.Feature(null, resCV.glob)]);
  print('CV - matriz (linhas = mapa, colunas = referência):', featuresMatriz(nCV, 0, CFG_LULC));
  print('CV - métricas por classe:', resCV.porClasse);
  print('CV - métricas globais:', globalCV);
  exportarCSV(featuresMatriz(nCV, 0, CFG_LULC), 'CV_matriz', colsMatriz(CFG_LULC));
  exportarCSV(resCV.porClasse, 'CV_por_classe', COLS_CLASSE_AMOSTRAL);
  exportarCSV(globalCV, 'CV_global', COLS_GLOBAL_AMOSTRAL);

  // ---- 4.5 Áreas do mapa LULC
  var nomesLULC = {'1': CFG_LULC.nomes[0], '2': CFG_LULC.nomes[1], '3': CFG_LULC.nomes[2],
                   '4': CFG_LULC.nomes[3], '5': CFG_LULC.nomes[4]};
  var areasLULC = areaPorClasse(classificado, 'LULC Random Forest', nomesLULC);
  print('ÁREAS LULC (área de mapa, ainda sem ajuste):', areasLULC);
  exportarCSV(areasLULC, 'Areas_LULC_mapa', COLS_AREA);

  // ---- 4.6 NDBI: separabilidade por classe e calibração do limiar
  var estatNDBI = ee.List(pixels.reduceColumns({
    reducer: ee.Reducer.percentile([5, 25, 50, 75, 95]).combine(ee.Reducer.mean(), '', true)
               .combine(ee.Reducer.stdDev(), '', true).group({groupField: 1, groupName: 'class'}),
    selectors: ['NDBI', 'class']
  }).get('groups'));
  var fcEstat = ee.FeatureCollection(estatNDBI.map(function(g) {
    g = ee.Dictionary(g);
    var c = ee.Number(g.get('class')).int();
    return ee.Feature(null, g.set('classe_nome', ee.Dictionary(nomesLULC).get(c.format())).set('ano', ANO));
  }));
  print('NDBI nas amostras por classe (percentis) — sobreposição urbano x solo:', fcEstat);
  exportarCSV(fcEstat, 'NDBI_estatisticas_por_classe',
              ['ano', 'class', 'classe_nome', 'p5', 'p25', 'p50', 'p75', 'p95', 'mean', 'stdDev']);

  var curva = curvaLimiares(pixels);
  exportarCSV(curva, 'NDBI_curva_limiares', COLS_CURVA);
  var melhor = ee.Feature(curva.sort(CRITERIO_LIMIAR, false).first());
  var limiarCalc = ee.Number(melhor.get('limiar'));
  var limiar = (LIMIAR_NDBI_FIXO === null) ? limiarCalc : ee.Number(LIMIAR_NDBI_FIXO);
  print('Limiar ótimo do NDBI pelas amostras (' + CRITERIO_LIMIAR + '):', melhor);
  print('Desempenho dos limiares da literatura (0 = Zha et al., 2003; 0,2 = Muhaimin et al., 2022):',
        curva.filter(ee.Filter.inList('limiar', [0, 0.2])));
  print('LIMIAR DO NDBI USADO (anote para o script de 2025):', limiar);
  print(ui.Chart.feature.byFeature(curva, 'limiar', ['TPR_urbana', 'FPR_soloExposto', 'FPR_vegRasteira', 'FPR_medio'])
    .setOptions({title: 'NDBI: acerto em Área Urbana x inclusão indevida das outras classes (' + ANO + ')',
                 hAxis: {title: 'Limiar do NDBI'}, vAxis: {title: 'Fração dos pixels de treino com NDBI > limiar'}}));

  // ---- 4.7 Produtos do NDBI
  var naoAgua = mndwi.lte(LIMIAR_MNDWI);
  var mascaraValida = ndbi.mask();
  // (A) Zha et al. (2003) original: NDBI > 0 e NDVI <= 0
  var zha = ndbi.gt(0).and(ndvi.lte(0)).rename('NDBI_Zha2003');
  // (B) Muhaimin et al. (2022): 1 < 0; 2 = 0 a 0,2; 3 > 0,2
  var muhaimin = ee.Image(1).where(ndbi.gte(0), 2).where(ndbi.gt(0.2), 3)
                   .updateMask(mascaraValida).clip(aoi).rename('NDBI_Muhaimin2022');
  // (C) Calibrado: NDBI > limiar calibrado, sem água (MNDWI)
  var calibrado = ndbi.gt(limiar).and(naoAgua).rename('NDBI_calibrado');
  // (D) Refinado: calibrado, retirando o que o RF classificou como Solo Exposto
  //     (resolve a confusão espectral solo exposto x construído; He et al., 2010)
  var refinado = calibrado.and(classificado.neq(CLASSE_SOLO)).rename('NDBI_refinado');
  var produto = (PRODUTO_NDBI === 'refinado' ? refinado : calibrado)
                  .unmask(0).updateMask(mascaraValida).clip(aoi).rename('NDBI_bin');

  Map.addLayer(ndbi, {min: -0.4, max: 0.3, palette: ['1a9641', 'ffffbf', 'd7191c']}, '4. NDBI contínuo', false);
  Map.addLayer(zha.selfMask(), {palette: ['FF00FF']}, '5. NDBI Zha (2003)', false);
  Map.addLayer(muhaimin, {min: 1, max: 3, palette: ['BFBFBF', 'FFD700', 'FF0000']}, '6. NDBI Muhaimin (2022)', false);
  Map.addLayer(calibrado.selfMask(), {palette: ['FFA500']}, '7. NDBI calibrado', false);
  Map.addLayer(refinado.selfMask(), {palette: ['FF0000']}, '8. NDBI refinado (sem solo exposto)');

  var nomesBin = {'0': 'Não construído', '1': 'Construído/impermeável'};
  var nomes3 = {'1': 'Não construído (NDBI < 0)', '2': 'Transição (0 a 0,2)', '3': 'Construído (NDBI > 0,2)'};
  var areasNDBI = areaPorClasse(zha.unmask(0).updateMask(mascaraValida), 'Zha et al. (2003)', nomesBin)
    .merge(areaPorClasse(muhaimin, 'Muhaimin et al. (2022)', nomes3))
    .merge(areaPorClasse(calibrado.unmask(0).updateMask(mascaraValida), 'NDBI calibrado', nomesBin))
    .merge(areaPorClasse(refinado.unmask(0).updateMask(mascaraValida), 'NDBI refinado', nomesBin))
    .map(function(f) { return f.set('limiar_calibrado', limiar); });
  print('ÁREAS DO NDBI POR PRODUTO (ha e %):', areasNDBI);
  exportarCSV(areasNDBI, 'Areas_NDBI', COLS_AREA.concat(['limiar_calibrado']));

  // ---- 4.8 Pontos de validação independentes
  var mapaFinal = classificado.toByte().addBands(produto.toByte());

  // Pixels disponíveis por classe do mapa (confere se cada estrato comporta os pontos)
  var pixelsPorClasse = classificado.reduceRegion({
    reducer: ee.Reducer.frequencyHistogram(), geometry: aoi, crs: CRS, scale: ESCALA,
    maxPixels: 1e13, tileScale: 16}).get('classification');
  print('Pixels mapeados por classe (1 a 5) — Água deve ter bem mais que ' + N_PONTOS[2] + ':', pixelsPorClasse);

  if (GERAR_PONTOS) {
    var ptsLULC = gerarPontos(mapaFinal, 'classification', CFG_LULC.ids, N_PONTOS, 'Pontos_Validacao_LULC' + ASSET_SUFIXO);
    var ptsNDBI = gerarPontos(mapaFinal, 'NDBI_bin', CFG_NDBI.ids, N_PONTOS_NDBI, 'Pontos_Validacao_NDBI' + ASSET_SUFIXO);
    Map.addLayer(ptsLULC, {color: 'white'}, '9. Pontos LULC', false);
    Map.addLayer(ptsNDBI, {color: 'cyan'}, '10. Pontos NDBI', false);
  } else {
    print('GERAR_PONTOS = false: nenhum ponto novo foi gerado.');
  }

  // ---- 4.9 Exportações
  exportarImagem(classificado.toByte(), 'LULC_classificacao');
  exportarImagem(zha.unmask(0).addBands(muhaimin).addBands(calibrado.unmask(0)).addBands(refinado.unmask(0))
                   .updateMask(mascaraValida).toByte(), 'NDBI_produtos');
  exportarImagem(ndbi.toFloat(), 'NDBI_continuo');
  Export.image.toAsset({image: mapaFinal, description: 'Asset_LULC_' + DESC, assetId: ASSET_MAPA,
                        crs: CRS, scale: ESCALA, region: aoi, maxPixels: 1e13});
}

// ============================
// 5 - EXECUÇÃO
// ============================
etapaMapear();

// ====================================================================
// NOTAS
// - Limiar do NDBI: calibrado pelo índice J de Youden (1950) sobre as amostras
//   de treino; será validado com pontos independentes (Olofsson et al., 2014).
// - Água: classe rara (lagos pequenos + trecho do rio Paraná na foz). Recebe
//   menos pontos (N_PONTOS[2]); isso é previsto no desenho estratificado de
//   Olofsson et al. (2014), pois o estimador pondera cada estrato pela sua área.
// - 2025: polígonos de treino NOVOS, interpretados sobre o mosaico de 2025.
//   O limiar do NDBI é o calibrado em 2020 (-0,03), para a comparação 2020 x 2025
//   usar o mesmo critério. A curva de limiares de 2025 é impressa só como controle.
// ====================================================================
