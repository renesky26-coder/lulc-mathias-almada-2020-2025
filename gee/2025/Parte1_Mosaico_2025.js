// ====================================================================
// LULC - BACIA DO RIO MATHIAS ALMADA (FOZ DO IGUAÇU-PR)
// PARTE 1 - MOSAICO SENTINEL-2 + ÍNDICES + NDBI CLASSIFICADO | ANO 2025
//
// Import necessário: table (limite da bacia).
//
// O que este script faz:
//  1) seleciona as cenas Sentinel-2 L2A (S2_SR_HARMONIZED) da janela definida;
//  2) mascara nuvem, sombra e cirro (SCL + Cloud Score+);
//  3) gera o mosaico de mediana com NDVI, MNDWI e NDBI;
//  4) classifica o NDBI por três critérios da literatura (seção 7);
//  5) mostra camadas de apoio à coleta de amostras;
//  6) exporta: lista de cenas, mosaico como ASSET (lido pela Parte 2),
//     GeoTIFFs dos índices e do NDBI classificado, e tabela de áreas do NDBI.
//
// SCRIPT DE 2025: mesma janela (jun-out), mesmos filtros e índices do script de 2020.
// ====================================================================

// ============================
// 1 - PARÂMETROS
// ============================
var ANO = 2025;

// Janela sazonal (DATA_FIM é EXCLUSIVA). Use os MESMOS meses em 2025.
var DATA_INICIO = '2025-06-01';
var DATA_FIM = '2025-11-01';     // inclui até 31/10/2025

var NUVENS_MAX = 10;             // % máx. de nuvem da CENA (CLOUDY_PIXEL_PERCENTAGE)
var CS_LIMIAR = 0.60;            // Cloud Score+ (cs_cdf) mínimo para pixel "limpo"
var MIN_OBS = 1;                 // nº mínimo de observações válidas por pixel

// Limiares dos índices (ver referências no final do script)
var LIMIAR_MNDWI = 0;            // água: MNDWI > 0 (Xu, 2006)
var LIMIAR_NDBI_TRANSICAO = 0;   // Muhaimin et al. (2022): < 0 não construído
var LIMIAR_NDBI_CONSTRUIDO = 0.2;//                         > 0,2 construído
// Otsu: null = calcula automaticamente neste ano. Para comparar 2020 x 2025
// com o MESMO critério, informe aqui um valor fixo (ex.: o Otsu de 2025).
var LIMIAR_OTSU_FIXO = null;

var CRS = 'EPSG:32721';          // WGS 84 / UTM 21S
var ESCALA = 10;

// Reprodutibilidade: se CENAS_FIXAS não estiver vazia, o script usa EXATAMENTE
// essas cenas (coluna 'id' do CSV Cenas_S2_...) e ignora datas e filtro de nuvem.
var CENAS_FIXAS = [];

var EXPORTAR = true;             // false = só visualizar, sem criar tarefas

var ASSET_BASE = 'projects/SEU-PROJETO-GEE/assets/';   // <- troque pelo seu projeto do Earth Engine
var AREA = 'MathiasAlmada';
var DESC = AREA + '_' + ANO;
var PASTA = 'LULC_' + DESC;
var ASSET_MOSAICO = ASSET_BASE + 'Mosaico_' + DESC;   // lido pela Parte 2

var bandas_S2 = ['B2', 'B3', 'B4', 'B8', 'B11', 'B12'];
var indices = ['NDVI', 'MNDWI', 'NDBI'];
var bandasAsset = bandas_S2.concat(indices);   // a Parte 2 escolhe as previsoras

var aoi = table.geometry();
Map.centerObject(aoi, 13);
Map.setOptions('SATELLITE');

// ============================
// 2 - FUNÇÕES
// ============================
// Máscara de pixel: SCL (0 sem dado, 1 saturado, 3 sombra, 8/9 nuvem, 10 cirro)
// e Cloud Score+ abaixo do limiar.
function mascarar(image) {
  var scl = image.select('SCL');
  var sclRuim = scl.eq(0).or(scl.eq(1)).or(scl.eq(3))
                   .or(scl.eq(8)).or(scl.eq(9)).or(scl.eq(10));
  var limpo = sclRuim.not().and(image.select('cs_cdf').gte(CS_LIMIAR));
  return image.updateMask(limpo)
              .select(bandas_S2)
              .divide(10000)
              .copyProperties(image, ['system:time_start']);
}

// NDVI (Rouse et al., 1974): (B8 - B4) / (B8 + B4)
// MNDWI (Xu, 2006): (B3 - B11) / (B3 + B11)
// NDBI (Zha et al., 2003): (B11 - B8) / (B11 + B8)  [SWIR1 e NIR]
function addIndices(image) {
  var ndvi = image.normalizedDifference(['B8', 'B4']).rename('NDVI');
  var mndwi = image.normalizedDifference(['B3', 'B11']).rename('MNDWI');
  var ndbi = image.normalizedDifference(['B11', 'B8']).rename('NDBI');
  return image.addBands([ndvi, mndwi, ndbi]);
}

// Limiar de Otsu (1979) a partir de um histograma do GEE
function otsu(histograma) {
  var h = ee.Dictionary(histograma);
  var counts = ee.Array(h.get('histogram'));
  var means = ee.Array(h.get('bucketMeans'));
  var size = means.length().get([0]);
  var total = counts.reduce(ee.Reducer.sum(), [0]).get([0]);
  var soma = means.multiply(counts).reduce(ee.Reducer.sum(), [0]).get([0]);
  var media = soma.divide(total);
  var bss = ee.List.sequence(1, size.subtract(1)).map(function(i) {
    var aCounts = counts.slice(0, 0, i);
    var aCount = aCounts.reduce(ee.Reducer.sum(), [0]).get([0]);
    var aMean = means.slice(0, 0, i).multiply(aCounts)
                     .reduce(ee.Reducer.sum(), [0]).get([0]).divide(aCount);
    var bCount = total.subtract(aCount);
    var bMean = soma.subtract(aCount.multiply(aMean)).divide(bCount);
    return aCount.multiply(aMean.subtract(media).pow(2))
                 .add(bCount.multiply(bMean.subtract(media).pow(2)));
  });
  return ee.Number(means.slice(0, 0, size.subtract(1)).toList().sort(bss).get(-1));
}

// Área (ha e %) por classe de uma imagem categórica inteira
function areaPorClasse(img, metodo, nomes, areaTotal) {
  var grupos = ee.Image.pixelArea().divide(10000).addBands(img.toInt()).reduceRegion({
    reducer: ee.Reducer.sum().group({groupField: 1, groupName: 'classe'}),
    geometry: aoi, crs: CRS, scale: ESCALA, maxPixels: 1e13, tileScale: 16
  }).get('groups');
  return ee.FeatureCollection(ee.List(grupos).map(function(g) {
    g = ee.Dictionary(g);
    var c = ee.Number(g.get('classe')).int();
    var a = ee.Number(g.get('sum'));
    return ee.Feature(null, {
      ano: ANO, metodo: metodo, classe: c,
      classe_nome: ee.Dictionary(nomes).get(c.format()),
      area_ha: a, area_pct: a.divide(areaTotal).multiply(100)
    });
  }));
}

// ============================
// 3 - COLEÇÃO SENTINEL-2
// ============================
var s2 = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED');
var csPlus = ee.ImageCollection('GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED');

var colecaoBruta = (CENAS_FIXAS.length > 0)
  ? s2.filter(ee.Filter.inList('system:index', CENAS_FIXAS)).filterBounds(aoi)
  : s2.filterBounds(aoi)
      .filterDate(DATA_INICIO, DATA_FIM)
      .filter(ee.Filter.lte('CLOUDY_PIXEL_PERCENTAGE', NUVENS_MAX));

var colecaoLigada = colecaoBruta.linkCollection(csPlus, ['cs_cdf']);
var colecao = colecaoLigada.map(mascarar);

// ============================
// 4 - DIAGNÓSTICO DAS CENAS (registrar na metodologia)
// ============================
print('==== PARTE 1 - MOSAICO ' + DESC + ' ====');
print('Data de execução do script:', new Date().toISOString());
print('Área da bacia (ha):', aoi.area(1).divide(10000));
if (CENAS_FIXAS.length > 0) {
  print('Modo CENAS_FIXAS: esperado ' + CENAS_FIXAS.length + ' cenas; encontradas:', colecaoBruta.size());
} else {
  print('Janela: ' + DATA_INICIO + ' a ' + DATA_FIM + ' (fim exclusivo)');
}
print('Cenas selecionadas (nuvem da cena <= ' + NUVENS_MAX + '%):', colecaoBruta.size());
print('Datas de aquisição:', colecaoBruta.aggregate_array('system:time_start')
  .map(function(t) { return ee.Date(t).format('YYYY-MM-dd'); }));
print('Tiles MGRS:', colecaoBruta.aggregate_histogram('MGRS_TILE'));
print('Satélites:', colecaoBruta.aggregate_histogram('SPACECRAFT_NAME'));
print('Baseline de processamento:', colecaoBruta.aggregate_histogram('PROCESSING_BASELINE'));
print('Nuvem média da cena (%):', colecaoBruta.aggregate_mean('CLOUDY_PIXEL_PERCENTAGE'));
print('Cenas com Cloud Score+ disponível [true/false]:',
      colecaoLigada.map(function(i) {
        return i.set('tem_cs', i.bandNames().contains('cs_cdf'));
      }).aggregate_histogram('tem_cs'));
print('Versão do modelo Cloud Score+:',
      csPlus.filterBounds(aoi).filterDate(DATA_INICIO, DATA_FIM).aggregate_histogram('MODEL_VERSION'));

// ============================
// 5 - MOSAICO DE MEDIANA E ÍNDICES
// ============================
var nObs = colecao.select('B4').count().unmask(0).clip(aoi).rename('n_obs');
var mosaico = addIndices(colecao.median()).clip(aoi).updateMask(nObs.gte(MIN_OBS));

var redutorMedia = {
  reducer: ee.Reducer.mean(), geometry: aoi, crs: CRS, scale: ESCALA,
  maxPixels: 1e13, tileScale: 16
};
print('Observações válidas por pixel (média):', nObs.reduceRegion(redutorMedia));
print('Observações válidas por pixel (mín/máx):', nObs.reduceRegion({
  reducer: ee.Reducer.minMax(), geometry: aoi, crs: CRS, scale: ESCALA, maxPixels: 1e13, tileScale: 16}));
print('% da bacia sem nenhuma observação válida:', nObs.eq(0).multiply(100).reduceRegion(redutorMedia));
print('% da bacia com menos de 3 observações válidas:', nObs.lt(3).multiply(100).reduceRegion(redutorMedia));
print('Bandas do asset (Parte 2):', mosaico.select(bandasAsset).bandNames());

var ndvi = mosaico.select('NDVI');
var mndwi = mosaico.select('MNDWI');
var ndbi = mosaico.select('NDBI');

print('Estatísticas dos índices na bacia (mín, máx, média, desvio):',
  mosaico.select(indices).reduceRegion({
    reducer: ee.Reducer.minMax().combine(ee.Reducer.mean(), '', true)
                                .combine(ee.Reducer.stdDev(), '', true),
    geometry: aoi, crs: CRS, scale: ESCALA, maxPixels: 1e13, tileScale: 16}));

// ============================
// 6 - MÁSCARA DE ÁGUA (MNDWI)
// ============================
var agua = mndwi.gt(LIMIAR_MNDWI).rename('agua_MNDWI');   // 1 = água
var naoAgua = agua.not();

// ============================
// 7 - NDBI CLASSIFICADO
// ============================
// (A) Método original de Zha et al. (2003): NDBI e NDVI recodificados em
//     binário (positivo = 1; não positivo = 0); construído = NDBIbin - NDVIbin > 0,
//     ou seja, NDBI > 0 e NDVI <= 0. É o critério do autor do índice.
var zha = ndbi.gt(0).subtract(ndvi.gt(0)).gt(0).rename('NDBI_Zha2003');   // 1 = construído

// (B) Três classes de Muhaimin et al. (2022), o limiar já usado no TCC:
//     1 = não construído (< 0); 2 = transição (0 a 0,2); 3 = construído (> 0,2)
var muhaimin = ee.Image(1)
  .where(ndbi.gte(LIMIAR_NDBI_TRANSICAO), 2)
  .where(ndbi.gt(LIMIAR_NDBI_CONSTRUIDO), 3)
  .updateMask(ndbi.mask()).clip(aoi).rename('NDBI_Muhaimin2022');

// (C) Limiar automático de Otsu (1979) no NDBI, com água mascarada pelo MNDWI,
//     como em Xi, Thinh e Li (2019) para Sentinel-2.
var histNDBI = ndbi.updateMask(naoAgua).reduceRegion({
  reducer: ee.Reducer.histogram({maxBuckets: 256}),
  geometry: aoi, crs: CRS, scale: ESCALA, maxPixels: 1e13, tileScale: 16
}).get('NDBI');
var limiarOtsuCalc = otsu(histNDBI);
var limiarOtsu = (LIMIAR_OTSU_FIXO === null) ? limiarOtsuCalc : ee.Number(LIMIAR_OTSU_FIXO);
print('Limiar de Otsu calculado para o NDBI de ' + ANO + ':', limiarOtsuCalc);
print('Limiar de Otsu USADO na classificação:', limiarOtsu);
var otsuBin = ndbi.gt(limiarOtsu).and(naoAgua).rename('NDBI_Otsu');   // 1 = construído

print('Histograma do NDBI (água excluída) — figura para o TCC:',
  ui.Chart.image.histogram({image: ndbi.updateMask(naoAgua), region: aoi, scale: ESCALA, maxBuckets: 200})
    .setOptions({title: 'NDBI ' + ANO + ' — bacia do rio Mathias Almada',
                 hAxis: {title: 'NDBI'}, vAxis: {title: 'Nº de pixels'}, legend: {position: 'none'}}));

// ---- 7.1 Tabela de áreas (ha e %) por método
var areaTotal = ee.Number(ee.Image.pixelArea().divide(10000).updateMask(ndbi.mask()).reduceRegion({
  reducer: ee.Reducer.sum(), geometry: aoi, crs: CRS, scale: ESCALA, maxPixels: 1e13, tileScale: 16
}).get('area'));
var nomesBin = {'0': 'Não construído', '1': 'Construído/impermeável'};
var nomes3 = {'1': 'Não construído (NDBI < 0)', '2': 'Transição (0 a 0,2)', '3': 'Construído (NDBI > 0,2)'};
var nomesAgua = {'0': 'Não água', '1': 'Água (MNDWI > 0)'};

var tabelaAreas = areaPorClasse(zha.unmask(0).updateMask(ndbi.mask()), 'Zha et al. (2003) binário', nomesBin, areaTotal)
  .merge(areaPorClasse(muhaimin, 'Muhaimin et al. (2022) 3 classes', nomes3, areaTotal))
  .merge(areaPorClasse(otsuBin.unmask(0).updateMask(ndbi.mask()), 'Otsu (1979) com máscara MNDWI', nomesBin, areaTotal))
  .merge(areaPorClasse(agua.unmask(0).updateMask(ndbi.mask()), 'Água MNDWI (Xu, 2006)', nomesAgua, areaTotal))
  .map(function(f) { return f.set('limiar_otsu', limiarOtsu); });
print('Área válida da bacia (ha):', areaTotal);
print('ÁREAS DO NDBI CLASSIFICADO (ha e %):', tabelaAreas);

// ============================
// 8 - CAMADAS DE APOIO À COLETA DE AMOSTRAS
// ============================
var contorno = ee.Image().byte().paint({featureCollection: ee.FeatureCollection(table), color: 1, width: 2});

Map.addLayer(mosaico, {bands: ['B4', 'B3', 'B2'], min: 0, max: 0.3, gamma: 1.4}, '1. RGB cor verdadeira');
Map.addLayer(mosaico, {bands: ['B8', 'B4', 'B3'], min: 0, max: 0.4}, '2. Falsa cor (vegetação em vermelho)', false);
Map.addLayer(mosaico, {bands: ['B12', 'B8', 'B4'], min: 0, max: 0.4}, '3. Falsa cor SWIR (urbano x solo exposto)', false);
Map.addLayer(ndvi, {min: -0.2, max: 0.9, palette: ['brown', 'yellow', 'green']}, '4. NDVI', false);
Map.addLayer(mndwi, {min: -0.5, max: 0.5, palette: ['white', 'blue']}, '5. MNDWI', false);
Map.addLayer(agua.selfMask(), {palette: ['00FFFF']}, '6. Água (MNDWI > 0)', false);
Map.addLayer(ndbi, {min: -0.4, max: 0.3, palette: ['1a9641', 'ffffbf', 'd7191c']}, '7. NDBI contínuo', false);
Map.addLayer(zha.selfMask(), {palette: ['FF0000']}, '8. NDBI - Zha et al. (2003)', false);
Map.addLayer(muhaimin, {min: 1, max: 3, palette: ['BFBFBF', 'FFD700', 'FF0000']}, '9. NDBI - Muhaimin et al. (2022)', false);
Map.addLayer(otsuBin.selfMask(), {palette: ['FF00FF']}, '10. NDBI - Otsu', false);
Map.addLayer(nObs, {min: 0, max: 15, palette: ['red', 'yellow', 'green']}, '11. Nº de observações válidas', false);
Map.addLayer(contorno, {palette: ['yellow']}, '12. Limite da bacia');

// ============================
// 9 - EXPORTAÇÕES
// ============================
if (EXPORTAR) {
  // 9.1 Lista de cenas (tabela da metodologia e preenchimento de CENAS_FIXAS)
  var tabelaCenas = ee.FeatureCollection(colecaoBruta.map(function(img) {
    return ee.Feature(null, {
      id: img.get('system:index'),
      data: img.date().format('YYYY-MM-dd'),
      satelite: img.get('SPACECRAFT_NAME'),
      tile: img.get('MGRS_TILE'),
      nuvem_cena_pct: img.get('CLOUDY_PIXEL_PERCENTAGE'),
      baseline: img.get('PROCESSING_BASELINE')
    });
  }));
  Export.table.toDrive({
    collection: tabelaCenas, description: 'Cenas_S2_' + DESC, folder: PASTA,
    fileFormat: 'CSV', selectors: ['id', 'data', 'satelite', 'tile', 'nuvem_cena_pct', 'baseline']
  });

  // 9.2 Tabela de áreas do NDBI classificado
  Export.table.toDrive({
    collection: tabelaAreas, description: 'Areas_NDBI_' + DESC, folder: PASTA,
    fileFormat: 'CSV', selectors: ['ano', 'metodo', 'classe', 'classe_nome', 'area_ha', 'area_pct', 'limiar_otsu']
  });

  // 9.3 Mosaico como ASSET (lido pela Parte 2): bandas + índices + n_obs
  Export.image.toAsset({
    image: mosaico.select(bandasAsset).addBands(nObs).toFloat(),
    description: 'Asset_Mosaico_' + DESC,
    assetId: ASSET_MOSAICO,
    crs: CRS, scale: ESCALA, region: aoi, maxPixels: 1e13
  });

  // 9.4 GeoTIFFs para o QGIS
  Export.image.toDrive({
    image: mosaico.select(bandas_S2).toFloat(),
    description: 'Mosaico_bandas_' + DESC, folder: PASTA,
    crs: CRS, scale: ESCALA, region: aoi, maxPixels: 1e13
  });
  Export.image.toDrive({
    image: mosaico.select(indices).toFloat(),
    description: 'Indices_NDVI_MNDWI_NDBI_' + DESC, folder: PASTA,
    crs: CRS, scale: ESCALA, region: aoi, maxPixels: 1e13
  });
  Export.image.toDrive({
    image: zha.unmask(0).addBands(muhaimin).addBands(otsuBin.unmask(0)).addBands(agua)
              .updateMask(ndbi.mask()).toByte(),
    description: 'NDBI_classificado_' + DESC, folder: PASTA,
    crs: CRS, scale: ESCALA, region: aoi, maxPixels: 1e13
  });
}

// ====================================================================
// NOTAS METODOLÓGICAS
// - B11 e B12 (20 m) são reamostradas para 10 m pelo vizinho mais próximo
//   (padrão do GEE) na exportação.
// - O filtro de nuvem da cena usa CLOUDY_PIXEL_PERCENTAGE.
// - O NDBI não separa bem área construída de solo exposto (Zha et al., 2003;
//   He et al., 2010). Por isso: água é mascarada pelo MNDWI e o resultado deve
//   ser cruzado com a classe "Solo Exposto" do Random Forest (Parte 2).
// - Para comparar 2020 x 2025 pelo Otsu, use o MESMO limiar (LIMIAR_OTSU_FIXO).
//
// REFERÊNCIAS DOS LIMIARES
// HE, C. et al. Improving the normalized difference built-up index to map urban
//   built-up areas using a semiautomatic segmentation approach. Remote Sensing
//   Letters, v. 1, n. 4, p. 213-221, 2010.
// MUHAIMIN, M. et al. Mapping build-up area density using NDBI and UI wetland in
//   the city Banjarmasin. IOP Conf. Ser.: Earth Environ. Sci., v. 1089, 012036, 2022.
// OTSU, N. A threshold selection method from gray-level histograms. IEEE Trans.
//   Systems, Man, and Cybernetics, v. 9, n. 1, p. 62-66, 1979.
// XI, Y.; THINH, N. X.; LI, C. Preliminary comparative assessment of various
//   spectral indices for built-up land derived from Landsat-8 OLI and Sentinel-2A
//   MSI imageries. European Journal of Remote Sensing, v. 52, n. 1, 2019.
// XU, H. Modification of normalised difference water index (NDWI) to enhance
//   open water features in remotely sensed imagery. International Journal of
//   Remote Sensing, v. 27, n. 14, p. 3025-3033, 2006.
// ZHA, Y.; GAO, J.; NI, S. Use of normalized difference built-up index in
//   automatically mapping urban areas from TM imagery. International Journal of
//   Remote Sensing, v. 24, n. 3, p. 583-594, 2003.
// ====================================================================
