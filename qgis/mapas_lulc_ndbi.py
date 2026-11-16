# -*- coding: utf-8 -*-
# =====================================================================
# MAPAS DO TCC - BACIA DO RIO MATHIAS ALMADA (2020 x 2025)
# Rodar no QGIS: Complementos > Terminal Python, e digitar:
#   exec(open(r'C:\CAMINHO\PARA\mapas_lulc_ndbi.py', encoding='utf-8').read())
#
# Gera (pasta 11_Analise_mudanca_2020_2025):
#   - Transicoes_LULC_2020_2025.tif + tabelas (matriz de transição e resumo, em ha)
#   - Novas_areas_urbanas_2020_2025.tif + tabela
#   - NDBI_refinado_2020/2025.tif (banda 4 sem o problema do canal Alpha)
# E três layouts (exportados em PNG 300 dpi na pasta "Mapas e Gráficos"):
#   Fig_LULC_2020_2025_transicoes | Fig_NDBI_2020_2025 | Fig_novas_areas_urbanas
# Grade de coordenadas em UTM (EPSG:32721), igual ao SRC dos dados.
# =====================================================================
import os
import numpy as np
from osgeo import gdal
from qgis.core import (QgsProject, QgsRasterLayer, QgsVectorLayer, QgsPalettedRasterRenderer,
                       QgsPrintLayout, QgsLayoutItemMap, QgsLayoutItemLabel, QgsLayoutItemLegend,
                       QgsLayoutItemScaleBar, QgsLayoutItemPicture, QgsLayoutItemMapGrid,
                       QgsLayoutExporter, QgsLayoutSize, QgsLayoutPoint, QgsUnitTypes,
                       QgsCoordinateReferenceSystem, QgsTextFormat, QgsLegendStyle,
                       QgsFillSymbol, QgsRasterRange, QgsWkbTypes, QgsRectangle,
                       QgsLegendRenderer, QgsMapLayerLegendUtils)
from qgis.PyQt.QtGui import QColor, QFont
from qgis.PyQt.QtCore import QRectF, Qt

BASE = r'C:\CAMINHO\PARA\DADOS'
D20 = os.path.join(BASE, 'LULC_MathiasAlmada_2020', '09_Mapas_GeoTIFF')
D25 = os.path.join(BASE, 'LULC_MathiasAlmada_2025', '09_Mapas_GeoTIFF')
OUT = os.path.join(BASE, '11_Analise_mudanca_2020_2025')
FIG = os.path.join(BASE, 'Mapas e Gráficos')
os.makedirs(OUT, exist_ok=True)
os.makedirs(FIG, exist_ok=True)

ARQ = {
    'l5_20': os.path.join(D20, 'LULC_classificacao_MathiasAlmada_2020.tif'),
    'l5_25': os.path.join(D25, 'LULC_classificacao_MathiasAlmada_2025.tif'),
    'l4_20': os.path.join(D20, 'LULC_4classes_MathiasAlmada_2020.tif'),
    'l4_25': os.path.join(D25, 'LULC_4classes_MathiasAlmada_2025.tif'),
    'nd_20': os.path.join(D20, 'NDBI_produtos_MathiasAlmada_2020.tif'),
    'nd_25': os.path.join(D25, 'NDBI_produtos_MathiasAlmada_2025.tif'),
}
HA = 0.01  # área de um pixel de 10 x 10 m, em hectares
FONTE = 'Arial'
GRADE_M = 2000  # intervalo da grade UTM (m)

print('================ MAPAS TCC 2020 x 2025 ================')
for k, v in ARQ.items():
    print(('OK      ' if os.path.exists(v) else 'FALTANDO') + '  ' + v)
TEM_L5_20 = os.path.exists(ARQ['l5_20'])

# ---------------------------------------------------------------------
# 1. LEITURA E GRAVAÇÃO
# ---------------------------------------------------------------------
def ler(path, banda=1):
    ds = gdal.Open(path)
    a = ds.GetRasterBand(banda).ReadAsArray()
    return a, ds.GetGeoTransform(), ds.GetProjection()

def gravar(path, arr, gt, prj):
    if os.path.exists(path):
        QgsProject.instance().removeMapLayers(
            [l.id() for l in QgsProject.instance().mapLayers().values()
             if l.source().replace('/', '\\').lower() == path.lower()])
        try:
            os.remove(path)
        except OSError:
            pass
    ds = gdal.GetDriverByName('GTiff').Create(path, arr.shape[1], arr.shape[0], 1,
                                              gdal.GDT_Byte, ['COMPRESS=LZW'])
    ds.SetGeoTransform(gt)
    ds.SetProjection(prj)
    b = ds.GetRasterBand(1)
    b.WriteArray(arr.astype(np.uint8))
    b.SetNoDataValue(0)   # 0 = fora da bacia (transparente)
    ds = None

def salvar_csv(path, cabecalho, linhas):
    with open(path, 'w', encoding='utf-8-sig') as f:
        f.write(';'.join(cabecalho) + '\n')
        for l in linhas:
            f.write(';'.join(str(x).replace('.', ',') if isinstance(x, float) else str(x) for x in l) + '\n')

l4_20, GT, PRJ = ler(ARQ['l4_20'])
l4_25, _, _ = ler(ARQ['l4_25'])
nd_20, _, _ = ler(ARQ['nd_20'], 4)   # banda 4 = NDBI refinado (validado)
nd_25, _, _ = ler(ARQ['nd_25'], 4)
valido = (l4_20 > 0) & (l4_25 > 0)   # pixels dentro da bacia nos dois anos
print('Área válida da bacia (ha): %.1f' % (valido.sum() * HA))

# ---------------------------------------------------------------------
# 2. NDBI REFINADO SEM CANAL ALPHA (1 = permeável, 2 = impermeável)
# ---------------------------------------------------------------------
for ano, nd in (('2020', nd_20), ('2025', nd_25)):
    gravar(os.path.join(OUT, 'NDBI_refinado_%s.tif' % ano), np.where(valido, nd + 1, 0), GT, PRJ)

# ---------------------------------------------------------------------
# 3. TRANSIÇÕES LULC (5 classes, pixel a pixel)
# ---------------------------------------------------------------------
NOMES5 = {1: 'Vegetação Densa', 2: 'Vegetação Rasteira', 3: 'Água', 4: 'Solo Exposto', 5: 'Área Urbana'}
TRANS = [  # código, cor, rótulo
    (1, '#e6e6e6', 'Sem mudança'),
    (2, '#8c2d04', 'Veg. Densa → Solo Exposto'),
    (3, '#fd8d3c', 'Veg. Densa → Veg. Rasteira'),
    (4, '#d7191c', 'Veg. Densa → Urbana'),
    (5, '#e7298a', 'Rasteira/Solo → Urbana'),
    (6, '#fee391', 'Veg. Rasteira ↔ Solo Exposto'),
    (7, '#1a9641', 'Ganho de Veg. Densa'),
    (8, '#9ecae1', 'Outras transições'),
]
if TEM_L5_20:
    a, _, _ = ler(ARQ['l5_20'])
    b, _, _ = ler(ARQ['l5_25'])
    v5 = valido & (a > 0) & (b > 0)
    t = np.full(a.shape, 8, np.uint8)
    t[a == b] = 1
    t[(a == 1) & (b == 4)] = 2
    t[(a == 1) & (b == 2)] = 3
    t[(a == 1) & (b == 5)] = 4
    t[np.isin(a, [2, 4]) & (b == 5)] = 5
    t[((a == 2) & (b == 4)) | ((a == 4) & (b == 2))] = 6
    t[(a != 1) & (b == 1)] = 7
    t[~v5] = 0
    gravar(os.path.join(OUT, 'Transicoes_LULC_2020_2025.tif'), t, GT, PRJ)
    tot = v5.sum() * HA
    mat = []
    for i in range(1, 6):
        lin = [NOMES5[i]]
        for j in range(1, 6):
            lin.append(round(float(((a == i) & (b == j) & v5).sum() * HA), 2))
        lin.append(round(float(((a == i) & v5).sum() * HA), 2))
        mat.append(lin)
    mat.append(['Total 2025'] + [round(float(((b == j) & v5).sum() * HA), 2) for j in range(1, 6)] + [round(float(tot), 2)])
    salvar_csv(os.path.join(OUT, 'Matriz_transicao_LULC_2020_2025_ha.csv'),
               ['2020 \\ 2025'] + [NOMES5[j] for j in range(1, 6)] + ['Total 2020'], mat)
    res = [[rot, round(float((t == c).sum() * HA), 2), round(float((t == c).sum() * HA / tot * 100), 2)]
           for c, _, rot in TRANS]
    salvar_csv(os.path.join(OUT, 'Resumo_transicoes_LULC_2020_2025.csv'), ['Transição', 'Área (ha)', '% da bacia'], res)
    print('--- Transições 2020 → 2025 (ha | % da bacia) ---')
    for r in res:
        print('  %-36s %9.2f  %6.2f%%' % tuple(r))
else:
    print('ATENÇÃO: falta LULC_classificacao_MathiasAlmada_2020.tif (5 classes). '
          'Baixe do Drive (pasta LULC_MathiasAlmada_2020) para 2020\\09_Mapas_GeoTIFF e rode de novo. '
          'O mapa de transições não será gerado agora.')

# ---------------------------------------------------------------------
# 4. NOVAS ÁREAS URBANAS / IMPERMEÁVEIS
# ---------------------------------------------------------------------
u20, u25 = l4_20 == 5, l4_25 == 5
i20, i25 = nd_20 == 1, nd_25 == 1
novo_lulc = u25 & ~u20
novo_ndbi = i25 & ~i20
nu = np.full(l4_20.shape, 4, np.uint8)
nu[u20 & u25] = 1
nu[novo_lulc & novo_ndbi] = 2
nu[novo_lulc ^ novo_ndbi] = 3
nu[~valido] = 0
gravar(os.path.join(OUT, 'Novas_areas_urbanas_2020_2025.tif'), nu, GT, PRJ)
NOVAS = [
    (1, '#636363', 'Urbana em 2020 e 2025'),
    (2, '#d7191c', 'Nova: LULC e NDBI'),
    (3, '#fdae61', 'Nova: um só produto'),
    (4, '#f2f2f2', 'Demais coberturas'),
]
totv = valido.sum() * HA
resn = [[rot, round(float((nu == c).sum() * HA), 2), round(float((nu == c).sum() * HA / totv * 100), 2)]
        for c, _, rot in NOVAS]
resn.append(['Perda de área urbana (LULC: urbano em 2020, não em 2025)',
             round(float((u20 & ~u25 & valido).sum() * HA), 2),
             round(float((u20 & ~u25 & valido).sum() * HA / totv * 100), 2)])
salvar_csv(os.path.join(OUT, 'Resumo_novas_areas_urbanas_2020_2025.csv'), ['Categoria', 'Área (ha)', '% da bacia'], resn)
print('--- Novas áreas urbanas (ha | % da bacia) ---')
for r in resn:
    print('  %-58s %9.2f  %6.2f%%' % tuple(r))
NOVAS = [(c, cor, '%s (%s ha)' % (r, ('{:,.0f}'.format((nu == c).sum() * HA)).replace(',', '.'))) for c, cor, r in NOVAS]

# ---------------------------------------------------------------------
# 5. CAMADAS NO PROJETO
# ---------------------------------------------------------------------
proj = QgsProject.instance()
raiz = proj.layerTreeRoot()
grupo = raiz.findGroup('Mapas_TCC_2020_2025') or raiz.insertGroup(0, 'Mapas_TCC_2020_2025')

def adicionar(path, nome, itens):
    for l in proj.mapLayersByName(nome):
        proj.removeMapLayer(l.id())
    lyr = QgsRasterLayer(path, nome)
    lyr.dataProvider().setUserNoDataValue(1, [QgsRasterRange(0, 0)])
    classes = [QgsPalettedRasterRenderer.Class(v, QColor(c), r) for v, c, r in itens]
    lyr.setRenderer(QgsPalettedRasterRenderer(lyr.dataProvider(), 1, classes))
    proj.addMapLayer(lyr, False)
    grupo.addLayer(lyr)
    return lyr

LULC4 = [(1, '#006400', 'Vegetação Densa'), (2, '#c8b560', 'Veg. Rasteira e Solo Exposto'),
         (3, '#0000ff', 'Água'), (5, '#ff0000', 'Área Urbana')]
NDBI = [(1, '#e0e0e0', 'Permeável'), (2, '#d7191c', 'Construída/impermeável')]

c_l20 = adicionar(ARQ['l4_20'], 'LULC 2020 (4 classes)', LULC4)
c_l25 = adicionar(ARQ['l4_25'], 'LULC 2025 (4 classes)', LULC4)
c_n20 = adicionar(os.path.join(OUT, 'NDBI_refinado_2020.tif'), 'NDBI refinado 2020', NDBI)
c_n25 = adicionar(os.path.join(OUT, 'NDBI_refinado_2025.tif'), 'NDBI refinado 2025', NDBI)
c_nu = adicionar(os.path.join(OUT, 'Novas_areas_urbanas_2020_2025.tif'), 'Novas áreas urbanas 2020–2025', NOVAS)
c_tr = adicionar(os.path.join(OUT, 'Transicoes_LULC_2020_2025.tif'), 'Transições LULC 2020–2025', TRANS) if TEM_L5_20 else None

# Limite da bacia: camada de polígono já aberta no projeto
bacia = None
for l in proj.mapLayers().values():
    if isinstance(l, QgsVectorLayer) and l.geometryType() == QgsWkbTypes.PolygonGeometry:
        n = l.name().lower()
        if any(s in n for s in ('almada', 'bacia', 'bh', 'limite')):
            bacia = l
            break
if bacia is None:
    raise Exception('Não achei o limite da bacia no projeto (camada de polígono com "almada", "bacia", "BH" ou "limite" no nome).')
print('Limite da bacia:', bacia.name())
bacia.setRenderer(bacia.renderer().__class__(QgsFillSymbol.createSimple(
    {'color': '0,0,0,0', 'outline_color': '0,0,0,255', 'outline_width': '0.35', 'style': 'no'})))
bacia.triggerRepaint()

crs_utm = QgsCoordinateReferenceSystem('EPSG:32721')
ext = QgsRectangle(GT[0], GT[3] + GT[5] * l4_20.shape[0], GT[0] + GT[1] * l4_20.shape[1], GT[3])
ext.grow(150)   # pequena margem em volta da bacia (m)

# ---------------------------------------------------------------------
# 6. DADOS DA VALIDAÇÃO (lidos das tabelas T6/T7 de cada ano)
# ---------------------------------------------------------------------
import csv

def ler_csv(path):
    with open(path, encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))

def t(ano, pasta, arq):
    return os.path.join(BASE, 'LULC_MathiasAlmada_%s' % ano, pasta, arq % ano)

VAL = {}
for ano in ('2020', '2025'):
    T6 = ler_csv(t(ano, '01_Resultados_finais_LULC_4classes', 'LULC4cl_T6_Metricas_classe_ajustadas_areas_MathiasAlmada_%s.csv'))
    T7 = ler_csv(t(ano, '01_Resultados_finais_LULC_4classes', 'LULC4cl_T7_Metricas_globais_MathiasAlmada_%s.csv'))[0]
    N6 = ler_csv(t(ano, '03_Validacao_NDBI', 'NDBI_T6_Metricas_classe_ajustadas_areas_MathiasAlmada_%s.csv'))
    N7 = ler_csv(t(ano, '03_Validacao_NDBI', 'NDBI_T7_Metricas_globais_MathiasAlmada_%s.csv'))[0]
    VAL[ano] = {
        'areas': {int(r['classe_id']): (float(r['area_ajustada_ha']), float(r['area_ajustada_IC95_ha']),
                                        float(r['area_mapa_ha'])) for r in T6},
        'oa': (float(T7['OA_pond_pct']), float(T7['OA_pond_IC95_pct']), float(T7['Kappa_pond'])),
        'imp': [(float(r['area_ajustada_ha']), float(r['area_ajustada_IC95_ha']), float(r['area_mapa_ha']))
                for r in N6 if r['classe_id'] == '1'][0],
        'oa_ndbi': (float(N7['OA_pond_pct']), float(N7['OA_pond_IC95_pct']), float(N7['Kappa_pond'])),
    }
def br(x, d=1):
    return ('{:,.%df}' % d).format(x).replace(',', 'X').replace('.', ',').replace('X', '.')

# ---------------------------------------------------------------------
# 7. GRÁFICOS (matplotlib) PARA OS PAINÉIS (d)
# ---------------------------------------------------------------------
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.rcParams.update({'font.family': 'Arial', 'font.size': 7, 'axes.linewidth': 0.6,
                     'xtick.major.width': 0.6, 'ytick.major.width': 0.6})
MM = 1 / 25.4

def grafico_barras(path, grupos, series, cores, ylabel, w_mm, h_mm, nota=None):
    fig, ax = plt.subplots(figsize=(w_mm * MM, h_mm * MM), dpi=300)
    n = len(series)
    larg = 0.8 / n
    x = np.arange(len(grupos))
    for k, (nome, vals, ics) in enumerate(series):
        pos = x - 0.4 + larg * (k + 0.5)
        ax.bar(pos, vals, larg * 0.92, yerr=ics, color=cores[k], edgecolor='black', linewidth=0.4,
               error_kw={'elinewidth': 0.6, 'capsize': 2, 'capthick': 0.6}, label=nome, zorder=3)
        for p, v in zip(pos, vals):
            ax.text(p, v * 0.5 if v > 150 else v + 40, br(v, 0), ha='center', va='center', fontsize=5.5,
                    color='white' if v > 150 and cores[k] in ('#4d4d4d', '#000000') else 'black',
                    rotation=90, zorder=4)
    ax.set_xticks(x)
    ax.set_xticklabels(grupos)
    ax.set_ylabel(ylabel)
    ax.yaxis.grid(True, linewidth=0.3, color='#bdbdbd', zorder=0)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.legend(frameon=False, fontsize=6.5, loc='upper left', ncol=n)
    ax.set_ylim(0, max(max(v + i for v, i in zip(s[1], s[2])) for s in series) * 1.22)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, p: br(v, 0)))
    if nota:
        ax.text(1.0, -0.2, nota, transform=ax.transAxes, ha='right', va='top', fontsize=5.5, style='italic')
    fig.tight_layout(pad=0.3)
    fig.savefig(path, dpi=300, transparent=True)
    plt.close(fig)

CL = [1, 2, 3, 5]
GR_LULC = os.path.join(OUT, 'grafico_areas_ajustadas_LULC.png')
grafico_barras(GR_LULC, ['Veg. Densa', 'Veg. Rasteira\ne Solo Exposto', 'Água', 'Área Urbana'],
               [('2020', [VAL['2020']['areas'][c][0] for c in CL], [VAL['2020']['areas'][c][1] for c in CL]),
                ('2025', [VAL['2025']['areas'][c][0] for c in CL], [VAL['2025']['areas'][c][1] for c in CL])],
               ['#bdbdbd', '#4d4d4d'], 'Área ajustada (ha) ± IC 95%', 128, 66,
               'Estimador estratificado de Olofsson et al. (2014)')
GR_IMP = os.path.join(OUT, 'grafico_areas_ajustadas_impermeavel.png')
grafico_barras(GR_IMP, ['Área Urbana (RF)', 'Sup. impermeável (NDBI)'],
               [('2020', [VAL['2020']['areas'][5][0], VAL['2020']['imp'][0]],
                         [VAL['2020']['areas'][5][1], VAL['2020']['imp'][1]]),
                ('2025', [VAL['2025']['areas'][5][0], VAL['2025']['imp'][0]],
                         [VAL['2025']['areas'][5][1], VAL['2025']['imp'][1]])],
               ['#bdbdbd', '#4d4d4d'], 'Área ajustada (ha) ± IC 95%', 128, 66,
               'Sobreposição dos IC 95%: diferença não significativa')

# Mudança do NDBI (1 permeável estável, 2 ganho, 3 perda, 4 impermeável estável)
nm = np.zeros(l4_20.shape, np.uint8)
nm[valido & ~i20 & ~i25] = 1
nm[valido & ~i20 & i25] = 2
nm[valido & i20 & ~i25] = 3
nm[valido & i20 & i25] = 4
gravar(os.path.join(OUT, 'Mudanca_NDBI_2020_2025.tif'), nm, GT, PRJ)
MUD_NDBI = [(1, '#f0f0f0', 'Permeável (estável)'), (4, '#636363', 'Impermeável (estável)'),
            (2, '#d7191c', 'Ganho de sup. impermeável'), (3, '#2c7bb6', 'Perda de sup. impermeável')]
MUD_NDBI = [(c, cor, '%s (%s ha)' % (r, br((nm == c).sum() * HA, 0))) for c, cor, r in MUD_NDBI]
c_nm = adicionar(os.path.join(OUT, 'Mudanca_NDBI_2020_2025.tif'), 'Mudança NDBI 2020–2025', MUD_NDBI)

# Rótulos das transições com a área (ha)
if c_tr:
    ttr, _, _ = ler(os.path.join(OUT, 'Transicoes_LULC_2020_2025.tif'))
    TRANS_HA = [(c, cor, '%s (%s ha)' % (r, br((ttr == c).sum() * HA, 0))) for c, cor, r in TRANS]
    c_tr = adicionar(os.path.join(OUT, 'Transicoes_LULC_2020_2025.tif'), 'Transições LULC 2020–2025', TRANS_HA)

# Mosaico RGB 2025 (B4, B3, B2) para o detalhe
from qgis.core import QgsMultiBandColorRenderer, QgsContrastEnhancement, QgsRasterMinMaxOrigin
for l in proj.mapLayersByName('Sentinel-2 2025 (RGB)'):
    proj.removeMapLayer(l.id())
c_rgb = QgsRasterLayer(os.path.join(D25, 'Mosaico_bandas_MathiasAlmada_2025.tif'), 'Sentinel-2 2025 (RGB)')
c_rgb.setRenderer(QgsMultiBandColorRenderer(c_rgb.dataProvider(), 3, 2, 1))
c_rgb.setContrastEnhancement(QgsContrastEnhancement.StretchToMinimumMaximum, QgsRasterMinMaxOrigin.CumulativeCut)
proj.addMapLayer(c_rgb, False)
grupo.addLayer(c_rgb)

# Mapa de localização (OpenStreetMap)
for l in proj.mapLayersByName('OpenStreetMap'):
    proj.removeMapLayer(l.id())
c_osm = QgsRasterLayer('type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png&zmax=19&zmin=0',
                       'OpenStreetMap', 'wms')
if c_osm.isValid():
    proj.addMapLayer(c_osm, False)
    grupo.addLayer(c_osm)
else:
    c_osm = None
    print('Aviso: OpenStreetMap indisponível (sem internet); o mapa de localização será omitido.')

# ---------------------------------------------------------------------
# 8. ELEMENTOS DE LAYOUT (padrão de periódico)
# ---------------------------------------------------------------------
from qgis.core import QgsLayoutItemMapOverview, QgsLayoutItemShape, QgsLayoutMeasurement
PAG_W = 297
XL, GAP = 15, 12                    # margem esquerda (espaço p/ coordenadas) e espaço entre colunas
W = (PAG_W - XL - GAP - 6) / 2      # largura de cada painel
ASP = ext.width() / ext.height()

def fmt(tam, negrito=False, italico=False, cor='#000000'):
    f = QgsTextFormat()
    fn = QFont(FONTE)
    fn.setBold(negrito)
    fn.setItalic(italico)
    f.setFont(fn)
    f.setSize(tam)
    f.setColor(QColor(cor))
    return f

def novo_layout(nome):
    mgr = proj.layoutManager()
    for l in mgr.printLayouts():
        if l.name() == nome:
            mgr.removeLayout(l)
    lay = QgsPrintLayout(proj)
    lay.initializeDefaults()
    lay.setName(nome)
    lay.pageCollection().page(0).setPageSize(QgsLayoutSize(PAG_W, 210))
    mgr.addLayout(lay)
    return lay

def rotulo(lay, texto, x, y, w, h, tam=7, negrito=False, italico=False, html=False):
    lb = QgsLayoutItemLabel(lay)
    lb.setText(texto)
    lb.setTextFormat(fmt(tam, negrito, italico))
    if html:
        lb.setMode(QgsLayoutItemLabel.ModeHtml)
    lay.addLayoutItem(lb)
    lb.attemptMove(QgsLayoutPoint(x, y))
    lb.attemptResize(QgsLayoutSize(w, h))
    return lb

def grade(m, intervalo, esquerda=True):
    g = QgsLayoutItemMapGrid('UTM', m)
    g.setCrs(crs_utm)
    g.setIntervalX(intervalo)
    g.setIntervalY(intervalo)
    g.setStyle(QgsLayoutItemMapGrid.FrameAnnotationsOnly)
    g.setFrameStyle(QgsLayoutItemMapGrid.ExteriorTicks)
    g.setFrameWidth(1.2)
    g.setFramePenSize(0.25)
    g.setAnnotationEnabled(True)
    g.setAnnotationFormat(QgsLayoutItemMapGrid.CustomFormat)
    g.setAnnotationExpression("format_number(@grid_number, 0) || if(@grid_axis = 'x', ' E', ' N')")
    g.setAnnotationTextFormat(fmt(5.5))
    g.setAnnotationFrameDistance(0.6)
    for lado in (QgsLayoutItemMapGrid.Top, QgsLayoutItemMapGrid.Right):
        g.setAnnotationDisplay(QgsLayoutItemMapGrid.HideAll, lado)
    if not esquerda:
        g.setAnnotationDisplay(QgsLayoutItemMapGrid.HideAll, QgsLayoutItemMapGrid.Left)
    g.setAnnotationPosition(QgsLayoutItemMapGrid.OutsideMapFrame, QgsLayoutItemMapGrid.Left)
    g.setAnnotationPosition(QgsLayoutItemMapGrid.OutsideMapFrame, QgsLayoutItemMapGrid.Bottom)
    g.setAnnotationDirection(QgsLayoutItemMapGrid.VerticalDescending, QgsLayoutItemMapGrid.Left)
    m.grids().addGrid(g)

def mapa(lay, camadas, x, y, w, extensao, letra, titulo, intervalo=GRADE_M, com_bacia=True):
    h = w * extensao.height() / extensao.width()
    m = QgsLayoutItemMap(lay)
    m.attemptSetSceneRect(QRectF(x, y, w, h))
    m.setCrs(crs_utm)
    m.setLayers(([bacia] if com_bacia else []) + camadas)
    m.setKeepLayerSet(True)
    m.setExtent(extensao)
    m.setFrameEnabled(True)
    m.setFrameStrokeWidth(QgsLayoutMeasurement(0.3))
    lay.addLayoutItem(m)
    grade(m, intervalo)
    m.updateBoundingRect()
    # selo do painel: letra em negrito + título
    fundo = QgsLayoutItemShape(lay)
    fundo.setShapeType(QgsLayoutItemShape.Rectangle)
    fundo.setSymbol(QgsFillSymbol.createSimple({'color': '255,255,255,220', 'outline_style': 'no'}))
    lay.addLayoutItem(fundo)
    fundo.attemptMove(QgsLayoutPoint(x + 0.6, y + 0.6))
    fundo.attemptResize(QgsLayoutSize(4.5 + 1.45 * len(titulo), 4.6))
    rotulo(lay, '<b>(%s)</b> %s' % (letra, titulo), x + 1.2, y + 0.9, 4.5 + 1.45 * len(titulo), 4.5, 7, html=True)
    return m, h

def legenda(lay, camadas, x, y, w, titulo, colunas=1, tam=6.5):
    lg = QgsLayoutItemLegend(lay)
    lg.setTitle(titulo)
    lg.setAutoUpdateModel(False)
    raiz_lg = lg.model().rootGroup()
    raiz_lg.clear()
    for c in camadas:
        nl = raiz_lg.addLayer(c)
        QgsLegendRenderer.setNodeLegendStyle(nl, QgsLegendStyle.Hidden)
        nos = lg.model().layerLegendNodes(nl)
        ordem = [i for i, n in enumerate(nos) if not str(n.data(Qt.DisplayRole)).startswith(('Banda', 'Band'))]
        QgsMapLayerLegendUtils.setLegendNodeOrder(nl, ordem)
        lg.model().refreshLayerLegend(nl)
    lg.rstyle(QgsLegendStyle.Title).setTextFormat(fmt(7, True))
    lg.rstyle(QgsLegendStyle.Title).setMargin(QgsLegendStyle.Bottom, 1.2)
    lg.rstyle(QgsLegendStyle.SymbolLabel).setTextFormat(fmt(tam))
    lg.rstyle(QgsLegendStyle.Symbol).setMargin(QgsLegendStyle.Top, 0.8)
    lg.setSymbolWidth(4.5)
    lg.setSymbolHeight(3)
    lg.setColumnCount(colunas)
    lg.setSplitLayer(True)
    lg.setColumnSpace(4)
    lg.setBoxSpace(0.5)
    lg.setFrameEnabled(False)
    lg.setBackgroundEnabled(False)
    lay.addLayoutItem(lg)
    lg.attemptMove(QgsLayoutPoint(x, y))
    lg.adjustBoxSize()
    return lg

def norte(lay, x, y, tam=9):
    n = QgsLayoutItemPicture(lay)
    n.setPicturePath(':/images/north_arrows/layout_default_north_arrow.svg')
    lay.addLayoutItem(n)
    n.attemptMove(QgsLayoutPoint(x, y))
    n.attemptResize(QgsLayoutSize(tam * 0.7, tam))

def escala(lay, m, x, y, km=1, seg=2):
    e = QgsLayoutItemScaleBar(lay)
    e.setStyle('Single Box')
    e.setLinkedMap(m)
    e.setUnits(QgsUnitTypes.DistanceKilometers)
    e.setUnitLabel('km')
    e.setNumberOfSegments(seg)
    e.setNumberOfSegmentsLeft(0)
    e.setUnitsPerSegment(km)
    e.setHeight(1.3)
    e.setLineWidth(0.25)
    e.setTextFormat(fmt(6))
    lay.addLayoutItem(e)
    e.attemptMove(QgsLayoutPoint(x, y))
    e.update()
    return e

def figura(lay, path, x, y, w, h):
    p = QgsLayoutItemPicture(lay)
    p.setPicturePath(path)
    p.setResizeMode(QgsLayoutItemPicture.Zoom)
    lay.addLayoutItem(p)
    p.attemptMove(QgsLayoutPoint(x, y))
    p.attemptResize(QgsLayoutSize(w, h))
    return p

def localizacao(lay, x, y, w, h):
    if c_osm is None:
        return None
    m = QgsLayoutItemMap(lay)
    m.attemptSetSceneRect(QRectF(x, y, w, h))
    m.setCrs(crs_utm)
    m.setLayers([bacia, c_osm])
    m.setKeepLayerSet(True)
    e = QgsRectangle(ext)
    e.grow(9000)
    m.setExtent(e)
    m.setFrameEnabled(True)
    m.setFrameStrokeWidth(QgsLayoutMeasurement(0.3))
    lay.addLayoutItem(m)
    rotulo(lay, 'Localização (Foz do Iguaçu, PR)', x, y - 3.6, w, 3.4, 5.8, italico=True)
    return m

def quadro_info(lay, x, y, w, linhas):
    caixa = QgsLayoutItemShape(lay)
    caixa.setShapeType(QgsLayoutItemShape.Rectangle)
    caixa.setSymbol(QgsFillSymbol.createSimple({'color': '247,247,247,255', 'outline_color': '150,150,150,255',
                                                'outline_width': '0.2'}))
    import math, re
    car = max(40, int(w * 1.05))   # caracteres por linha (fonte 5,8 pt)
    h = sum(math.ceil(len(re.sub('<[^>]+>', '', l)) / car) for l in linhas) * 2.75 + 2.5
    lay.addLayoutItem(caixa)
    caixa.attemptMove(QgsLayoutPoint(x, y))
    caixa.attemptResize(QgsLayoutSize(w, h))
    rotulo(lay, '<br>'.join(linhas), x + 1.5, y + 1.0, w - 3, h - 1.5, 5.8, html=True)
    return h

def exportar(lay, nome_arq, altura):
    lay.pageCollection().page(0).setPageSize(QgsLayoutSize(PAG_W, altura))
    exp = QgsLayoutExporter(lay)
    cfg = QgsLayoutExporter.ImageExportSettings()
    cfg.dpi = 300
    destino = os.path.join(FIG, nome_arq + '.png')
    r = exp.exportToImage(destino, cfg)
    cfg_pdf = QgsLayoutExporter.PdfExportSettings()
    exp.exportToPdf(destino.replace('.png', '.pdf'), cfg_pdf)
    print(('Exportado: ' if r == QgsLayoutExporter.Success else 'ERRO ao exportar: ') + destino + ' (+ PDF)')

TXT_SRC = ('<b>Sistema de referência:</b> WGS 84 / UTM zona 21S (EPSG:32721)')
TXT_DADOS = ('<b>Dados:</b> Sentinel-2 MSI L2A (10 m), mosaicos de mediana jun–out/2020 e jun–out/2025 '
             '(Google Earth Engine)')
TXT_AUTOR = '<b>Elaboração:</b> o autor (2026)'
def txt_acur(chave, rot):
    a, b = VAL['2020'][chave], VAL['2025'][chave]
    return ('<b>%s (OA ponderada ± IC 95%%):</b> 2020: %s ± %s%% (κ = %s); 2025: %s ± %s%% (κ = %s)'
            % (rot, br(a[0]), br(a[1]), br(a[2], 2), br(b[0]), br(b[1]), br(b[2], 2)))

X2 = XL + W + GAP
LOC_W = 42

# ===== Figura 1: LULC 2020 | LULC 2025 / Transições | Áreas ajustadas =====
lay = novo_layout('Fig_LULC_2020_2025_transicoes')
y = 5
m1, h = mapa(lay, [c_l20], XL, y, W, ext, 'a', 'Uso e cobertura 2020')
m2, _ = mapa(lay, [c_l25], X2, y, W, ext, 'b', 'Uso e cobertura 2025')
y += h + 7
legenda(lay, [c_l20], XL, y, 2 * W + GAP, 'Classes de uso e cobertura da terra', colunas=4, tam=7)
y += 9
if c_tr:
    m3, _ = mapa(lay, [c_tr], XL, y, W, ext, 'c', 'Transições 2020–2025')
figura(lay, GR_LULC, X2, y + 5, W, h - 5)
rotulo(lay, '<b>(d)</b> Áreas ajustadas por classe (2020 × 2025)', X2, y + 0.5, 90, 4.5, 7, html=True)
y += h + 7
if c_tr:
    legenda(lay, [c_tr], XL, y, W, 'Transições (área em ha)', colunas=2, tam=6.2)
yb = y
norte(lay, X2, yb, 10)
escala(lay, m1, X2 + 10, yb + 3.5)
localizacao(lay, PAG_W - 6 - LOC_W, yb + 4, LOC_W, 26)
hq = quadro_info(lay, X2, yb + 13, W - LOC_W - 3,
                 [TXT_SRC, TXT_DADOS, 'Classificação Random Forest (100 árvores); validação independente estratificada (n = 220/ano)',
                  TXT_AUTOR])
y = yb + max(31, 13 + hq) + 2.5
rotulo(lay, txt_acur('oa', 'Exatidão LULC') + '. Transições calculadas pixel a pixel com as 5 classes originais '
       '(não validadas individualmente).', XL, y, 2 * W + GAP, 4, 6, html=True)
exportar(lay, 'Fig_LULC_2020_2025_transicoes', y + 7)

# ===== Figura 2: NDBI 2020 | 2025 / Mudança | Áreas ajustadas =====
lay = novo_layout('Fig_NDBI_2020_2025')
y = 5
m1, h = mapa(lay, [c_n20], XL, y, W, ext, 'a', 'NDBI refinado 2020')
m2, _ = mapa(lay, [c_n25], X2, y, W, ext, 'b', 'NDBI refinado 2025')
y += h + 7
legenda(lay, [c_n20], XL, y, 2 * W + GAP, 'Superfície (NDBI > −0,03; sem água e sem solo exposto)', colunas=2, tam=7)
y += 9
m3, _ = mapa(lay, [c_nm], XL, y, W, ext, 'c', 'Mudança da superfície impermeável')
figura(lay, GR_IMP, X2, y + 5, W, h - 5)
rotulo(lay, '<b>(d)</b> Áreas ajustadas: urbano (RF) e impermeável (NDBI)', X2, y + 0.5, 100, 4.5, 7, html=True)
y += h + 7
legenda(lay, [c_nm], XL, y, W, 'Mudança 2020–2025 (área em ha)', colunas=2, tam=6.2)
yb = y
norte(lay, X2, yb, 10)
escala(lay, m1, X2 + 10, yb + 3.5)
localizacao(lay, PAG_W - 6 - LOC_W, yb + 4, LOC_W, 26)
hq = quadro_info(lay, X2, yb + 13, W - LOC_W - 3,
                 [TXT_SRC, TXT_DADOS, 'NDBI (Zha; Gao; Ni, 2003): limiar calibrado (J de Youden) = −0,03; '
                  'água removida pelo MNDWI e solo exposto pelo RF', TXT_AUTOR])
y = yb + max(31, 13 + hq) + 2.5
rotulo(lay, txt_acur('oa_ndbi', 'Exatidão NDBI') + '. Mudança pixel a pixel sujeita aos erros de cada data.',
       XL, y, 2 * W + GAP, 4, 6, html=True)
exportar(lay, 'Fig_NDBI_2020_2025', y + 7)

# ===== Figura 3: Novas áreas urbanas + detalhe do loteamento =====
DET = QgsRectangle(746400, 7178350, 748000, 7179800)   # loteamento no setor centro-sul
lay = novo_layout('Fig_novas_areas_urbanas')
y = 5
m1, h = mapa(lay, [c_nu], XL, y, W, ext, 'a', 'Novas áreas urbanas 2020–2025')
ov = QgsLayoutItemMapOverview('detalhe', m1)
m1.overviews().addOverview(ov)
wd = (W - 6) / 2
md, hd = mapa(lay, [c_rgb], X2, y, wd, DET, 'b', 'Sentinel-2 2025 (RGB)', intervalo=500, com_bacia=False)
mn, _ = mapa(lay, [c_nu], X2 + wd + 6, y, wd, DET, 'c', 'Detalhe de (a)', intervalo=500, com_bacia=False)
ov.setLinkedMap(md)
ov.setFrameSymbol(QgsFillSymbol.createSimple({'color': '0,0,0,0', 'outline_color': '0,0,0,255',
                                              'outline_width': '0.5', 'outline_style': 'dash'}))
mn.grids().grid(0).setAnnotationDisplay(QgsLayoutItemMapGrid.HideAll, QgsLayoutItemMapGrid.Left)
escala(lay, md, X2, y + hd + 6.5, km=0.25, seg=2)
rotulo(lay, 'Escala de (b) e (c)', X2 + 45, y + hd + 6.5, 40, 3.5, 5.8, italico=True)
y += h + 7
legenda(lay, [c_nu], XL, y, W, 'Categorias (área em ha)', colunas=2, tam=6.5)
norte(lay, XL + W - 45, y + 9, 10)
escala(lay, m1, XL + W - 35, y + 12.5)
rotulo(lay, '<b>Nota:</b> em (b), loteamento com ruas pavimentadas e lotes ainda sem edificações; em (c), '
       'ele aparece como mosaico de pixels urbanos (vias) e não urbanos (lotes). Com pixels de 10 m, lotes, '
       'ruas e edificações isoladas não são resolvidos individualmente: as áreas indicadas são sinais '
       'localizados de expansão, e não uma estimativa estatisticamente significativa da mudança na escala da bacia.',
       X2, y, W, 14, 6.2, html=True)
y += 21
hq = quadro_info(lay, XL, y, W,
                 [TXT_SRC, TXT_DADOS, 'Nova área urbana = urbano em 2025 e não urbano em 2020 (RF, 4 classes) '
                  'e/ou ganho de superfície impermeável (NDBI)', TXT_AUTOR])
localizacao(lay, X2, y, LOC_W, 26)
rotulo(lay, txt_acur('oa', 'Exatidão LULC') + '<br><br>' + txt_acur('oa_ndbi', 'Exatidão NDBI'),
       X2 + LOC_W + 4, y + 2, W - LOC_W - 4, 20, 6, html=True)
y += max(hq, 31)
exportar(lay, 'Fig_novas_areas_urbanas', y + 4)

print('Concluído. Layouts em Projeto > Gerenciador de layouts; PNG e PDF em:', FIG)
