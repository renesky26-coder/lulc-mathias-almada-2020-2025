# -*- coding: utf-8 -*-
# =====================================================================
# MAPA DE SUSCETIBILIDADE A INUNDAÇÕES (HAND) - BACIA DO RIO MATHIAS ALMADA
# Rodar no QGIS (projeto Risco_Inund aberto): Complementos > Terminal Python:
#   exec(open(r'C:\CAMINHO\PARA\mapa_hand.py', encoding='utf-8').read())
# Usa as camadas abertas: raster com "Risco" no nome, limite da bacia e rios.
# Exporta: Mapas e Gráficos\Fig_suscetibilidade_HAND.png/.pdf e tabela CSV.
# =====================================================================
import os, csv, math, re
import numpy as np
from osgeo import gdal, ogr
from qgis.core import (QgsProject, QgsRasterLayer, QgsVectorLayer, QgsWkbTypes, QgsPrintLayout,
                       QgsLayoutItemMap, QgsLayoutItemLabel, QgsLayoutItemLegend, QgsLayoutItemScaleBar,
                       QgsLayoutItemPicture, QgsLayoutItemMapGrid, QgsLayoutExporter, QgsLayoutSize,
                       QgsLayoutPoint, QgsUnitTypes, QgsCoordinateReferenceSystem, QgsTextFormat,
                       QgsLegendStyle, QgsFillSymbol, QgsRasterRange, QgsRectangle, QgsLegendRenderer,
                       QgsMapLayerLegendUtils, QgsPalettedRasterRenderer, QgsSingleBandPseudoColorRenderer,
                       QgsLayoutItemShape, QgsLayoutMeasurement, QgsCoordinateTransform)
from qgis.PyQt.QtGui import QColor, QFont
from qgis.PyQt.QtCore import QRectF, Qt

BASE = r'C:\CAMINHO\PARA\DADOS'
OUT = os.path.join(BASE, '11_Analise_mudanca_2020_2025')
FIG = os.path.join(BASE, 'Mapas e Gráficos')
LULC25 = os.path.join(BASE, 'LULC_MathiasAlmada_2025', '09_Mapas_GeoTIFF', 'LULC_4classes_MathiasAlmada_2025.tif')
NDBI25 = os.path.join(OUT, 'NDBI_refinado_2025.tif')
FONTE = 'Arial'
proj = QgsProject.instance()
crs_utm = QgsCoordinateReferenceSystem('EPSG:32721')
print('============ MAPA HAND ============')

# ---------------- camadas do projeto ----------------
def achar(cond):
    for l in proj.mapLayers().values():
        if cond(l):
            return l
    return None
hand = achar(lambda l: isinstance(l, QgsRasterLayer) and 'risco' in l.name().lower())
bacia = achar(lambda l: isinstance(l, QgsVectorLayer) and l.geometryType() == QgsWkbTypes.PolygonGeometry
              and any(s in l.name().lower() for s in ('bacia', 'almada', 'limite', 'bh')))
rios = achar(lambda l: isinstance(l, QgsVectorLayer) and l.geometryType() == QgsWkbTypes.LineGeometry)
print('HAND :', hand.name() if hand else 'NÃO ENCONTRADO', '|', hand.source() if hand else '')
print('Bacia:', bacia.name() if bacia else 'NÃO ENCONTRADO')
print('Rios :', rios.name() if rios else 'NÃO ENCONTRADO')
if hand is None or bacia is None:
    raise Exception('Abra o projeto Risco_Inund (raster de risco e limite da bacia).')

NOMES = {1: 'Muito Alta (0–1 m)', 2: 'Alta (1–5 m)', 3: 'Média (5–10 m)', 4: 'Baixa (10–25 m)', 5: 'Muito Baixa (> 25 m)'}
CURTO = {1: 'Muito Alta', 2: 'Alta', 3: 'Média', 4: 'Baixa', 5: 'Muito Baixa'}
CORES = {1: '#b2182b', 2: '#ef8a62', 3: '#fddbc7', 4: '#a6d96a', 5: '#1a9641'}
# tenta usar as cores já definidas no projeto
r = hand.renderer()
try:
    if isinstance(r, QgsPalettedRasterRenderer):
        for c in r.classes():
            v = int(round(c.value))
            if v in CORES:
                CORES[v] = c.color.name()
    elif isinstance(r, QgsSingleBandPseudoColorRenderer):
        its = r.shader().rasterShaderFunction().colorRampItemList()
        if len(its) >= 5 and all(abs(it.value - round(it.value)) < 1e-6 and 1 <= it.value <= 5 for it in its[:5]):
            for it in its:
                CORES[int(round(it.value))] = it.color.name()
except Exception as e:
    print('Aviso cores:', e)
print('Cores:', CORES)

# ---------------- grade de 10 m (igual ao LULC/NDBI) recortada pela bacia ----------------
ref = gdal.Open(NDBI25)
gt = ref.GetGeoTransform()
nx, ny = ref.RasterXSize, ref.RasterYSize
bounds = (gt[0], gt[3] + gt[5] * ny, gt[0] + gt[1] * nx, gt[3])
HAND_TIF = os.path.join(OUT, 'HAND_m_12m.tif')
src_hand = HAND_TIF if os.path.exists(HAND_TIF) else hand.source().split('|')[0]
print('Fonte do HAND usada:', src_hand)
src_bacia = bacia.source().split('|')[0]
lyrname = None
if 'layername=' in bacia.source():
    lyrname = bacia.source().split('layername=')[1].split('|')[0]
kw = dict(format='MEM', dstSRS='EPSG:32721', outputBounds=bounds, width=nx, height=ny,
          resampleAlg='near', cutlineDSName=src_bacia, dstNodata=-9999)
if lyrname:
    kw['cutlineLayer'] = lyrname
dh = gdal.Warp('', src_hand, **kw)
a = dh.GetRasterBand(1).ReadAsArray().astype(float)
nd = dh.GetRasterBand(1).GetNoDataValue()
valid = np.isfinite(a) & (a != -9999)
if nd is not None and nd != -9999:
    valid &= (a != nd)
vmax = np.nanmax(a[valid])
print('Valor máximo do raster HAND na bacia:', vmax)
if vmax > 5.5:   # raster contínuo em metros -> reclassifica (Tabela 3)
    cls = np.zeros(a.shape, np.uint8)
    for k, (lo, hi) in enumerate([(-1e9, 1), (1, 5), (5, 10), (10, 25), (25, 1e9)], start=1):
        cls[valid & (a >= lo) & (a < hi)] = k
else:
    cls = np.where(valid, np.round(a), 0).astype(np.uint8)
HA = abs(gt[1] * gt[5]) / 10000.0
area = {k: (cls == k).sum() * HA for k in range(1, 6)}
tot = sum(area.values())
print('Área total (ha):', round(tot, 1))

ds_l = gdal.Open(LULC25)

# --- diagnóstico do efeito de borda: classe 1 a até 100 m do limite da bacia ---
dentro = cls > 0
er = dentro.copy()
for _ in range(10):
    e2 = er.copy()
    e2[1:, :] &= er[:-1, :]; e2[:-1, :] &= er[1:, :]; e2[:, 1:] &= er[:, :-1]; e2[:, :-1] &= er[:, 1:]
    er = e2
borda = dentro & ~er
a1b = ((cls == 1) & borda).sum() * HA
print('DIAG borda: classe Muito Alta na faixa de 100 m do limite = %.1f ha (%.1f%% da classe); faixa total = %.1f ha' % (a1b, a1b / max(area[1], 1e-9) * 100, borda.sum() * HA))
for k in range(1, 6):
    print('DIAG classe %d na faixa de borda: %.1f ha' % (k, ((cls == k) & borda).sum() * HA))
lulc = ds_l.GetRasterBand(1).ReadAsArray()
print('LULC shape', lulc.shape, 'NDBI', (ny, nx))
ndbi = ref.GetRasterBand(1).ReadAsArray()
LUL = [(1, 'Vegetação Densa', '#006400'), (2, 'Veg. Rasteira e Solo Exposto', '#c8b560'),
       (3, 'Água', '#0000ff'), (5, 'Área Urbana', '#ff0000')]
comp, imp = {}, {}
for k in range(1, 6):
    m = cls == k
    n = max(m.sum(), 1)
    comp[k] = [((lulc == c) & m).sum() / n * 100 for c, _, _ in LUL]
    imp[k] = ((ndbi == 2) & m).sum() / n * 100
# urbano/impermeável total em cada classe (ha)
csvp = os.path.join(OUT, 'Suscetibilidade_HAND_areas_e_ocupacao_2025.csv')
with open(csvp, 'w', encoding='utf-8-sig', newline='') as f:
    w = csv.writer(f, delimiter=';')
    w.writerow(['Classe de suscetibilidade', 'Área (ha)', '% da bacia'] + ['%% %s (2025)' % n for _, n, _ in LUL]
               + ['% superfície impermeável NDBI (2025)'])
    for k in range(1, 6):
        w.writerow([NOMES[k], ('%.1f' % area[k]).replace('.', ','), ('%.1f' % (area[k] / tot * 100)).replace('.', ',')]
                   + [('%.1f' % v).replace('.', ',') for v in comp[k]] + [('%.1f' % imp[k]).replace('.', ',')])
print('Tabela:', csvp)
for k in range(1, 6):
    print('%-22s %8.1f ha %5.1f%% | urbano %5.1f%% | impermeável %5.1f%%' % (NOMES[k], area[k], area[k] / tot * 100, comp[k][3], imp[k]))

def br(x, d=1):
    return ('{:,.%df}' % d).format(x).replace(',', 'X').replace('.', ',').replace('X', '.')

# ---------------- camada classificada (para o mapa, recortada pela bacia) ----------------
tifp = os.path.join(OUT, 'Suscetibilidade_HAND_10m.tif')
for l in proj.mapLayersByName('Suscetibilidade HAND'):
    proj.removeMapLayer(l.id())
try:
    if os.path.exists(tifp):
        os.remove(tifp)
except OSError:
    pass
ds = gdal.GetDriverByName('GTiff').Create(tifp, nx, ny, 1, gdal.GDT_Byte, ['COMPRESS=LZW'])
ds.SetGeoTransform(gt); ds.SetProjection(ref.GetProjection())
b = ds.GetRasterBand(1); b.WriteArray(cls); b.SetNoDataValue(0); ds = None
c_h = QgsRasterLayer(tifp, 'Suscetibilidade HAND')
c_h.dataProvider().setUserNoDataValue(1, [QgsRasterRange(0, 0)])
c_h.setRenderer(QgsPalettedRasterRenderer(c_h.dataProvider(), 1,
    [QgsPalettedRasterRenderer.Class(k, QColor(CORES[k]), '%s – %s ha (%s%%)' % (NOMES[k], br(area[k], 0), br(area[k] / tot * 100)))
     for k in range(1, 6)]))
proj.addMapLayer(c_h, False)
proj.layerTreeRoot().insertLayer(0, c_h)
bacia.setRenderer(bacia.renderer().__class__(QgsFillSymbol.createSimple(
    {'color': '0,0,0,0', 'outline_color': '0,0,0,255', 'outline_width': '0.4', 'style': 'no'})))
bacia.triggerRepaint()
ext = QgsRectangle(bounds[0], bounds[1], bounds[2], bounds[3])
ext.grow(150)

# ---------------- gráficos ----------------
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.rcParams.update({'font.family': 'Arial', 'font.size': 7, 'axes.linewidth': 0.6,
                     'xtick.major.width': 0.6, 'ytick.major.width': 0.6})
MM = 1 / 25.4
ks = [1, 2, 3, 4, 5]

def g_area(path, w_mm, h_mm):
    fig, ax = plt.subplots(figsize=(w_mm * MM, h_mm * MM), dpi=300)
    y = np.arange(5)[::-1]
    vals = [area[k] for k in ks]
    ax.barh(y, vals, 0.68, color=[CORES[k] for k in ks], edgecolor='black', linewidth=0.4, zorder=3)
    for yy, v in zip(y, vals):
        ax.text(v + max(vals) * 0.015, yy, '%s ha  (%s%%)' % (br(v, 0), br(v / tot * 100)), va='center', fontsize=6.3)
    ax.set_yticks(y); ax.set_yticklabels([CURTO[k] for k in ks])
    ax.set_xlim(0, max(vals) * 1.42)
    ax.set_xlabel('Área (ha)')
    ax.xaxis.grid(True, linewidth=0.3, color='#bdbdbd', zorder=0)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, p: br(v, 0)))
    for s in ('top', 'right'): ax.spines[s].set_visible(False)
    fig.tight_layout(pad=0.3); fig.savefig(path, dpi=300, transparent=True); plt.close(fig)

def g_comp(path, w_mm, h_mm):
    fig, ax = plt.subplots(figsize=(w_mm * MM, h_mm * MM), dpi=300)
    y = np.arange(5)[::-1]
    esq = np.zeros(5)
    for j, (_, nome, cor) in enumerate(LUL):
        v = np.array([comp[k][j] for k in ks])
        ax.barh(y, v, 0.68, left=esq, color=cor, edgecolor='black', linewidth=0.3, label=nome, zorder=3)
        for yy, vv, ee in zip(y, v, esq):
            if vv >= 7:
                ax.text(ee + vv / 2, yy, br(vv, 0), ha='center', va='center', fontsize=5.8,
                        color='white' if cor in ('#006400', '#0000ff', '#ff0000') else 'black')
        esq += v
    for yy, k in zip(y, ks):
        ax.text(102, yy, br(imp[k], 0) + '%', va='center', fontsize=6.3, fontweight='bold')
    ax.text(102, 4.62, 'Imperm.\n(NDBI)', fontsize=5.5, va='bottom', style='italic')
    ax.set_yticks(y); ax.set_yticklabels([CURTO[k] for k in ks])
    ax.set_xlim(0, 100); ax.set_xlabel('Participação na classe de suscetibilidade (%)')
    for s in ('top', 'right'): ax.spines[s].set_visible(False)
    ax.legend(frameon=False, fontsize=5.6, ncol=2, loc='upper center', bbox_to_anchor=(0.45, -0.3),
              handlelength=1.2, columnspacing=0.8)
    fig.tight_layout(pad=0.3); fig.savefig(path, dpi=300, transparent=True); plt.close(fig)

RW = 92
GA = os.path.join(OUT, 'grafico_HAND_areas.png')
GC = os.path.join(OUT, 'grafico_HAND_ocupacao_2025.png')
g_area(GA, RW, 50)
g_comp(GC, RW, 58)

# ---------------- layout ----------------
def fmt(tam, negrito=False, italico=False):
    f = QgsTextFormat(); fn = QFont(FONTE); fn.setBold(negrito); fn.setItalic(italico)
    f.setFont(fn); f.setSize(tam); f.setColor(QColor('#000000')); return f

def rotulo(lay, texto, x, y, w, h, tam=7, html=True, italico=False):
    lb = QgsLayoutItemLabel(lay); lb.setText(texto); lb.setTextFormat(fmt(tam, italico=italico))
    if html: lb.setMode(QgsLayoutItemLabel.ModeHtml)
    lay.addLayoutItem(lb); lb.attemptMove(QgsLayoutPoint(x, y)); lb.attemptResize(QgsLayoutSize(w, h)); return lb

def figura(lay, path, x, y, w, h):
    p = QgsLayoutItemPicture(lay); p.setPicturePath(path); p.setResizeMode(QgsLayoutItemPicture.Zoom)
    lay.addLayoutItem(p); p.attemptMove(QgsLayoutPoint(x, y)); p.attemptResize(QgsLayoutSize(w, h)); return p

PAG_W = 210
mgr = proj.layoutManager()
for l in mgr.printLayouts():
    if l.name() == 'Fig_suscetibilidade_HAND':
        mgr.removeLayout(l)
lay = QgsPrintLayout(proj); lay.initializeDefaults(); lay.setName('Fig_suscetibilidade_HAND')
lay.pageCollection().page(0).setPageSize(QgsLayoutSize(PAG_W, 297)); mgr.addLayout(lay)

XL, Y0 = 13, 4
MW = PAG_W - XL - 5
MH = MW * ext.height() / ext.width()
m = QgsLayoutItemMap(lay)
m.attemptSetSceneRect(QRectF(XL, Y0, MW, MH)); m.setCrs(crs_utm)
m.setLayers([bacia] + ([rios] if rios else []) + [c_h]); m.setKeepLayerSet(True)
m.setExtent(ext); m.setFrameEnabled(True); m.setFrameStrokeWidth(QgsLayoutMeasurement(0.3))
lay.addLayoutItem(m)
g = QgsLayoutItemMapGrid('UTM', m); g.setCrs(crs_utm); g.setIntervalX(2000); g.setIntervalY(2000)
g.setStyle(QgsLayoutItemMapGrid.FrameAnnotationsOnly); g.setFrameStyle(QgsLayoutItemMapGrid.ExteriorTicks)
g.setFrameWidth(1.2); g.setFramePenSize(0.25); g.setAnnotationEnabled(True)
g.setAnnotationFormat(QgsLayoutItemMapGrid.CustomFormat)
g.setAnnotationExpression("format_number(@grid_number, 0) || if(@grid_axis = 'x', ' E', ' N')")
g.setAnnotationTextFormat(fmt(5.5)); g.setAnnotationFrameDistance(0.6)
for lado in (QgsLayoutItemMapGrid.Top, QgsLayoutItemMapGrid.Right):
    g.setAnnotationDisplay(QgsLayoutItemMapGrid.HideAll, lado)
g.setAnnotationPosition(QgsLayoutItemMapGrid.OutsideMapFrame, QgsLayoutItemMapGrid.Left)
g.setAnnotationPosition(QgsLayoutItemMapGrid.OutsideMapFrame, QgsLayoutItemMapGrid.Bottom)
g.setAnnotationDirection(QgsLayoutItemMapGrid.VerticalDescending, QgsLayoutItemMapGrid.Left)
m.grids().addGrid(g); m.updateBoundingRect()
fundo = QgsLayoutItemShape(lay); fundo.setShapeType(QgsLayoutItemShape.Rectangle)
fundo.setSymbol(QgsFillSymbol.createSimple({'color': '255,255,255,220', 'outline_style': 'no'}))
lay.addLayoutItem(fundo); fundo.attemptMove(QgsLayoutPoint(XL + 0.6, Y0 + MH - 5.2)); fundo.attemptResize(QgsLayoutSize(68, 4.6))
rotulo(lay, '<b>(a)</b> Suscetibilidade a inundações (modelo HAND)', XL + 1.2, Y0 + MH - 4.9, 70, 4.5)

# legenda + norte/escala logo abaixo do mapa
yb = Y0 + MH + 6.5
lg = QgsLayoutItemLegend(lay); lg.setTitle('Classes de suscetibilidade (altura acima da drenagem mais próxima)')
lg.setAutoUpdateModel(False); rg = lg.model().rootGroup(); rg.clear()
nl = rg.addLayer(c_h); QgsLegendRenderer.setNodeLegendStyle(nl, QgsLegendStyle.Hidden)
nos = lg.model().layerLegendNodes(nl)
QgsMapLayerLegendUtils.setLegendNodeOrder(nl, [i for i, n in enumerate(nos) if not str(n.data(Qt.DisplayRole)).startswith(('Banda', 'Band'))])
if rios:
    nr = rg.addLayer(rios); QgsLegendRenderer.setNodeLegendStyle(nr, QgsLegendStyle.Hidden)
    QgsMapLayerLegendUtils.setLegendNodeUserLabel(nr, 0, 'Rede de drenagem')
nb = rg.addLayer(bacia); QgsMapLayerLegendUtils.setLegendNodeUserLabel(nb, 0, 'Limite da bacia'); QgsLegendRenderer.setNodeLegendStyle(nb, QgsLegendStyle.Hidden)
for n in rg.children():
    lg.model().refreshLayerLegend(n)
lg.rstyle(QgsLegendStyle.Title).setTextFormat(fmt(7, True)); lg.rstyle(QgsLegendStyle.Title).setMargin(QgsLegendStyle.Bottom, 1.2)
lg.rstyle(QgsLegendStyle.SymbolLabel).setTextFormat(fmt(6.3)); lg.rstyle(QgsLegendStyle.Symbol).setMargin(QgsLegendStyle.Top, 0.8)
lg.setSymbolWidth(4.5); lg.setSymbolHeight(3); lg.setColumnCount(2); lg.setSplitLayer(True); lg.setColumnSpace(5)
lg.setBoxSpace(0.5); lg.setFrameEnabled(False); lg.setBackgroundEnabled(False)
lay.addLayoutItem(lg); lg.attemptMove(QgsLayoutPoint(XL, yb)); lg.adjustBoxSize()
nrt = QgsLayoutItemPicture(lay); nrt.setPicturePath(':/images/north_arrows/layout_default_north_arrow.svg')
lay.addLayoutItem(nrt); nrt.attemptMove(QgsLayoutPoint(PAG_W - 52, yb)); nrt.attemptResize(QgsLayoutSize(7, 10))
e = QgsLayoutItemScaleBar(lay); e.setStyle('Single Box'); e.setLinkedMap(m); e.setUnits(QgsUnitTypes.DistanceKilometers)
e.setUnitLabel('km'); e.setNumberOfSegments(2); e.setNumberOfSegmentsLeft(0); e.setUnitsPerSegment(1)
e.setHeight(1.3); e.setLineWidth(0.25); e.setTextFormat(fmt(6)); lay.addLayoutItem(e)
e.attemptMove(QgsLayoutPoint(PAG_W - 42, yb + 2)); e.update()
lay.refresh()

# gráficos lado a lado
yg = yb + 25
GX2 = XL + RW + (MW - 2 * RW)
rotulo(lay, '<b>(b)</b> Área por classe de suscetibilidade', XL, yg, RW, 4.5)
figura(lay, GA, XL, yg + 4.5, RW, 50)
rotulo(lay, '<b>(c)</b> Uso e cobertura (2025) em cada classe', GX2, yg, RW, 4.5)
figura(lay, GC, GX2, yg + 4.5, RW, 58)
qy = yg + 4.5 + 58 + 1

linhas = ['<b>Sistema de referência:</b> WGS 84 / UTM zona 21S (EPSG:32721)',
          '<b>Dados:</b> HAND calculado a partir do MDE ALOS PALSAR (12,5 m) com margem de 3 km em torno da bacia (preenchimento de depressões, direção de fluxo D8, acúmulo de fluxo, drenagem ≥ 1.000 células) e reclassificado conforme a Tabela 3; uso e cobertura 2025 (Random Forest) e NDBI refinado 2025 (Sentinel-2, 10 m)',
          '<b>Nota:</b> (b) e (c) obtidos por contagem de pixels na grade de 10 m (valores não ajustados pela validação). <b>Elaboração:</b> o autor (2026)']
qw = MW
car = int(qw * 1.05)
qh = sum(math.ceil(len(re.sub('<[^>]+>', '', l)) / car) for l in linhas) * 2.75 + 2.5
cx = QgsLayoutItemShape(lay); cx.setShapeType(QgsLayoutItemShape.Rectangle)
cx.setSymbol(QgsFillSymbol.createSimple({'color': '247,247,247,255', 'outline_color': '150,150,150,255', 'outline_width': '0.2'}))
lay.addLayoutItem(cx); cx.attemptMove(QgsLayoutPoint(XL, qy)); cx.attemptResize(QgsLayoutSize(qw, qh))
rotulo(lay, '<br>'.join(linhas), XL + 1.5, qy + 1.0, qw - 3, qh - 1.5, 5.8)

alt = qy + qh + 3
lay.pageCollection().page(0).setPageSize(QgsLayoutSize(PAG_W, alt))
exp = QgsLayoutExporter(lay)
cfg = QgsLayoutExporter.ImageExportSettings(); cfg.dpi = 300
dest = os.path.join(FIG, 'Fig_suscetibilidade_HAND.png')
rr = exp.exportToImage(dest, cfg)
exp.exportToPdf(dest.replace('.png', '.pdf'), QgsLayoutExporter.PdfExportSettings())
print(('Exportado: ' if rr == QgsLayoutExporter.Success else 'ERRO: ') + dest)
