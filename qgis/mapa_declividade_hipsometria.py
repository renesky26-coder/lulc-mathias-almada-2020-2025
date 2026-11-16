# -*- coding: utf-8 -*-
# =====================================================================
# DECLIVIDADE (classes Embrapa) E HIPSOMETRIA - BACIA DO RIO MATHIAS ALMADA
#   exec(open(r'C:\CAMINHO\PARA\mapa_declividade_hipsometria.py', encoding='utf-8').read())
# MDE ALOS PALSAR 12,5 m com margem de 1 km (evita efeito de borda na declividade e no sombreamento).
# Saídas: Mapas e Gráficos\Fig_declividade_hipsometria.png/.pdf ; tabelas CSV em 11_Analise_mudanca_2020_2025
# =====================================================================
import os, csv, math, re, traceback
import numpy as np
from osgeo import gdal, ogr, osr
from qgis.core import (QgsProject, QgsRasterLayer, QgsVectorLayer, QgsWkbTypes, QgsPrintLayout, QgsLayoutItemMap,
                       QgsLayoutItemLabel, QgsLayoutItemLegend, QgsLayoutItemScaleBar, QgsLayoutItemPicture,
                       QgsLayoutItemMapGrid, QgsLayoutExporter, QgsLayoutSize, QgsLayoutPoint, QgsUnitTypes,
                       QgsCoordinateReferenceSystem, QgsTextFormat, QgsLegendStyle, QgsFillSymbol, QgsLineSymbol,
                       QgsRasterRange, QgsRectangle, QgsLegendRenderer, QgsMapLayerLegendUtils, QgsPalettedRasterRenderer,
                       QgsLayoutItemShape, QgsLayoutMeasurement, QgsCoordinateTransform, QgsSingleBandGrayRenderer,
                       QgsContrastEnhancement, QgsSingleSymbolRenderer, QgsTextBufferSettings)
from qgis.PyQt.QtGui import QColor, QFont, QPainter
from qgis.PyQt.QtCore import QRectF, Qt

LOG = open(r'C:\CAMINHO\PARA\DADOS\log_declividade.txt', 'w', encoding='utf-8')
def log(*a):
    s = ' '.join(str(x) for x in a); print(s); LOG.write(s + '\n'); LOG.flush()
try:
    BASE = r'C:\CAMINHO\PARA\DADOS'
    OUT = os.path.join(BASE, '11_Analise_mudanca_2020_2025')
    FIG = os.path.join(BASE, 'Mapas e Gráficos')
    DEM = r'C:\CAMINHO\PARA\MDE_12m.tif'
    FONTE = 'Arial'
    RES, MARGEM = 12.5, 1000.0
    proj = QgsProject.instance()
    crs = QgsCoordinateReferenceSystem('EPSG:32721')
    def achar(cond):
        for l in proj.mapLayers().values():
            if cond(l): return l
    bacia = achar(lambda l: isinstance(l, QgsVectorLayer) and l.geometryType() == QgsWkbTypes.PolygonGeometry and 'bacia' in l.name().lower() and l.name() != 'Limite da bacia')
    rios = achar(lambda l: isinstance(l, QgsVectorLayer) and l.geometryType() == QgsWkbTypes.LineGeometry and 'rio' in l.name().lower() and l.name() != 'Rede de drenagem')
    if not os.path.exists(DEM):
        DEM = achar(lambda l: isinstance(l, QgsRasterLayer) and 'dem' in l.name().lower()).source()
    log('Bacia:', bacia.name(), '| Rios:', rios.name() if rios else None, '| MDE:', DEM)

    # ---------- geometria da bacia em EPSG:32721 ----------
    tr = QgsCoordinateTransform(bacia.crs(), crs, proj)
    geoms = []
    for f in bacia.getFeatures():
        g = f.geometry(); g.transform(tr); geoms.append(g)
    from qgis.core import QgsGeometry
    gb = QgsGeometry.unaryUnion(geoms)
    e = gb.boundingBox()
    xmin = math.floor((e.xMinimum() - MARGEM) / RES) * RES; xmax = math.ceil((e.xMaximum() + MARGEM) / RES) * RES
    ymin = math.floor((e.yMinimum() - MARGEM) / RES) * RES; ymax = math.ceil((e.yMaximum() + MARGEM) / RES) * RES
    ds = gdal.Warp('', DEM, format='MEM', dstSRS='EPSG:32721', outputBounds=(xmin, ymin, xmax, ymax),
                   xRes=RES, yRes=RES, resampleAlg='bilinear', dstNodata=-9999)
    z = ds.GetRasterBand(1).ReadAsArray().astype(np.float64)
    gt, prj = ds.GetGeoTransform(), ds.GetProjection()
    ny, nx = z.shape
    log('MDE com margem: %d x %d' % (nx, ny), 'nodata', int((z <= -9000).sum()))

    # máscara da bacia
    drv = ogr.GetDriverByName('Memory'); vds = drv.CreateDataSource('m')
    sr = osr.SpatialReference(); sr.ImportFromEPSG(32721)
    vl = vds.CreateLayer('b', sr, ogr.wkbMultiPolygon)
    ft = ogr.Feature(vl.GetLayerDefn()); ft.SetGeometry(ogr.CreateGeometryFromWkt(gb.asWkt())); vl.CreateFeature(ft)
    mds = gdal.GetDriverByName('MEM').Create('', nx, ny, 1, gdal.GDT_Byte); mds.SetGeoTransform(gt); mds.SetProjection(prj)
    gdal.RasterizeLayer(mds, [1], vl, burn_values=[1], options=['ALL_TOUCHED=FALSE'])
    dentro = (mds.GetRasterBand(1).ReadAsArray() == 1) & (z > -9000)
    HA = RES * RES / 10000.0
    log('Área da bacia (ha):', round(dentro.sum() * HA, 1))

    # ---------- declividade (%) e sombreamento ----------
    sl = gdal.DEMProcessing('', ds, 'slope', format='MEM', slopeFormat='percent', computeEdges=True)
    s = sl.GetRasterBand(1).ReadAsArray().astype(np.float64)
    hs = gdal.DEMProcessing('', ds, 'hillshade', format='MEM', multiDirectional=True, zFactor=3, computeEdges=True)
    h = hs.GetRasterBand(1).ReadAsArray()
    sv = s[dentro]; zv = z[dentro]
    st = dict(smed=sv.mean(), smd=np.median(sv), smax=sv.max(), zmin=zv.min(), zmax=zv.max(), zmed=zv.mean())
    st['amp'] = st['zmax'] - st['zmin']; st['hi'] = (st['zmed'] - st['zmin']) / st['amp']
    log('Estatísticas:', {k: round(float(v), 3) for k, v in st.items()})

    EMB = [(1, 'Plano', 0, 3), (2, 'Suave ondulado', 3, 8), (3, 'Ondulado', 8, 20), (4, 'Forte ondulado', 20, 45),
           (5, 'Montanhoso', 45, 75), (6, 'Escarpado', 75, 1e9)]
    COR_D = {1: '#1a9641', 2: '#a6d96a', 3: '#ffffbf', 4: '#fdae61', 5: '#d7191c', 6: '#7b1d4f'}
    cd = np.zeros((ny, nx), np.uint8)
    for k, _, lo, hi in EMB:
        cd[dentro & (s >= lo) & (s < hi)] = k
    a_d = {k: (cd == k).sum() * HA for k, *_ in EMB}
    tot = sum(a_d.values())

    z0 = math.floor(st['zmin'] / 25.0) * 25; z1 = math.ceil(st['zmax'] / 25.0) * 25
    HIP = [(i + 1, z0 + 25 * i, z0 + 25 * (i + 1)) for i in range(int((z1 - z0) / 25))]
    PAL = ['#1b7837', '#5aae61', '#a6dba0', '#e7e9a1', '#f6d68a', '#e0b06b', '#bf8a52', '#97663f', '#73492e', '#5a3a28']
    COR_H = {k: PAL[i] for i, (k, _, _) in enumerate(HIP)}
    chp = np.zeros((ny, nx), np.uint8)
    for k, lo, hi in HIP:
        chp[dentro & (z >= lo) & (z < hi)] = k
    a_h = {k: (chp == k).sum() * HA for k, *_ in HIP}
    for k, n, lo, hi in EMB: log('Decliv %-16s %8.1f ha %5.1f%%' % (n, a_d[k], a_d[k] / tot * 100))
    for k, lo, hi in HIP: log('Hipso %d–%d m %8.1f ha %5.1f%%' % (lo, hi, a_h[k], a_h[k] / tot * 100))

    def br(x, d=1):
        return ('{:,.%df}' % d).format(x).replace(',', 'X').replace('.', ',').replace('X', '.')

    # ---------- GeoTIFFs ----------
    def salva(nome, arr, dtype, nodata):
        p = os.path.join(OUT, nome)
        for l in proj.mapLayers().values():
            if isinstance(l, QgsRasterLayer) and os.path.normcase(l.source()) == os.path.normcase(p):
                proj.removeMapLayer(l.id())
        try:
            if os.path.exists(p): os.remove(p)
        except OSError: p = p.replace('.tif', '_v2.tif')
        o = gdal.GetDriverByName('GTiff').Create(p, nx, ny, 1, dtype, ['COMPRESS=LZW'])
        o.SetGeoTransform(gt); o.SetProjection(prj); b = o.GetRasterBand(1); b.WriteArray(arr); b.SetNoDataValue(nodata); o = None
        return p
    p_d = salva('Declividade_Embrapa_12m.tif', cd, gdal.GDT_Byte, 0)
    p_h = salva('Hipsometria_classes_12m.tif', chp, gdal.GDT_Byte, 0)
    hh = np.where(dentro, h, 0).astype(np.uint8); hh[dentro & (hh == 0)] = 1
    p_s = salva('Sombreamento_12m.tif', hh, gdal.GDT_Byte, 0)
    s_out = np.where(dentro, s, -9999).astype(np.float32)
    salva('Declividade_percentual_12m.tif', s_out, gdal.GDT_Float32, -9999)

    with open(os.path.join(OUT, 'Declividade_Hipsometria_areas.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f, delimiter=';')
        w.writerow(['Declividade (Embrapa)', 'Intervalo (%)', 'Área (ha)', '% da bacia'])
        for k, n, lo, hi in EMB:
            w.writerow([n, ('%d–%d' % (lo, hi)) if hi < 1e8 else '> %d' % lo, br(a_d[k]), br(a_d[k] / tot * 100)])
        w.writerow([]); w.writerow(['Hipsometria (m)', '', 'Área (ha)', '% da bacia'])
        for k, lo, hi in HIP: w.writerow(['%d–%d' % (lo, hi), '', br(a_h[k]), br(a_h[k] / tot * 100)])
        w.writerow([]); w.writerow(['Declividade média (%)', br(st['smed'])]); w.writerow(['Declividade mediana (%)', br(st['smd'])])
        w.writerow(['Altitude mín./máx./média (m)', '%s / %s / %s' % (br(st['zmin'], 0), br(st['zmax'], 0), br(st['zmed'], 0))])
        w.writerow(['Amplitude altimétrica (m)', br(st['amp'], 0)]); w.writerow(['Integral hipsométrica', br(st['hi'], 2)])

    # ---------- camadas ----------
    for nm in ('Declividade (Embrapa)', 'Hipsometria', 'Sombreamento 12,5 m', 'Limite da bacia', 'Rede de drenagem'):
        for l in proj.mapLayersByName(nm): proj.removeMapLayer(l.id())
    ND = [k for k, *_ in EMB if a_d[k] > 0]
    def faixa(lo, hi): return ('%d–%d%%' % (lo, hi)) if hi < 1e8 else '> %d%%' % lo
    L_d = QgsRasterLayer(p_d, 'Declividade (Embrapa)')
    L_d.setRenderer(QgsPalettedRasterRenderer(L_d.dataProvider(), 1,
        [QgsPalettedRasterRenderer.Class(k, QColor(COR_D[k]), '%s (%s)' % (n, faixa(lo, hi))) for k, n, lo, hi in EMB if k in ND]))
    L_h = QgsRasterLayer(p_h, 'Hipsometria')
    L_h.setRenderer(QgsPalettedRasterRenderer(L_h.dataProvider(), 1,
        [QgsPalettedRasterRenderer.Class(k, QColor(COR_H[k]), '%d–%d m' % (lo, hi)) for k, lo, hi in HIP if a_h[k] > 0]))
    def sombra(nome, op=0.55):
        L = QgsRasterLayer(p_s, nome)
        r = QgsSingleBandGrayRenderer(L.dataProvider(), 1)
        ce = QgsContrastEnhancement(L.dataProvider().dataType(1)); ce.setMinimumValue(60); ce.setMaximumValue(255)
        ce.setContrastEnhancementAlgorithm(QgsContrastEnhancement.StretchToMinimumMaximum); r.setContrastEnhancement(ce)
        L.setRenderer(r); L.setBlendMode(QPainter.CompositionMode_Multiply); L.setOpacity(op)
        return L
    pass
    for L in (L_d, L_h): proj.addMapLayer(L, False)
    grp = proj.layerTreeRoot().findGroup('Figura declividade-hipsometria') or proj.layerTreeRoot().insertGroup(0, 'Figura declividade-hipsometria')
    for L in (L_d, L_h): grp.addLayer(L)
    grp.setItemVisibilityChecked(False)
    # estilos vetoriais em cópias de estilo (sem alterar o projeto original)
    B = QgsVectorLayer(bacia.source(), 'Limite da bacia', bacia.providerType())
    B.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({'color': '0,0,0,0', 'style': 'no', 'outline_color': '0,0,0,255', 'outline_width': '0.45'})))
    R = None
    if rios:
        R = QgsVectorLayer(rios.source(), 'Rede de drenagem', rios.providerType())
        R.setRenderer(QgsSingleSymbolRenderer(QgsLineSymbol.createSimple({'line_color': '#1f78b4', 'line_width': '0.3'})))
    for L in (B, R):
        if L: proj.addMapLayer(L, False); grp.addLayer(L)

    # ---------- FIGURA DE GRÁFICOS (separada, dois painéis lado a lado) ----------
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.family': 'Arial', 'font.size': 8, 'axes.linewidth': 0.6,
                         'xtick.major.width': 0.6, 'ytick.major.width': 0.6, 'xtick.labelsize': 7.5, 'ytick.labelsize': 7.5,
                         'xtick.major.size': 2.5, 'ytick.major.size': 2.5})
    MM = 1 / 25.4
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(165 * MM, 68 * MM), dpi=500, gridspec_kw={'wspace': 0.42})
    ks = ND; x = np.arange(len(ks)); v = np.array([a_d[k] / tot * 100 for k in ks])
    a1.bar(x, v, 0.7, color=[COR_D[k] for k in ks], edgecolor='black', linewidth=0.5, zorder=3)
    for xx, vv, k in zip(x, v, ks):
        a1.text(xx, vv + 1.2, '%s%%\n(%s ha)' % (br(vv), br(a_d[k], 0)), ha='center', va='bottom', fontsize=6.6, linespacing=1.05)
    a1.set_xticks(x); a1.set_xticklabels(['%s\n%s' % (n.replace('Suave ondulado', 'Suave\nondulado').replace('Forte ondulado', 'Forte\nondulado'),
                                           faixa(lo, hi)) for k, n, lo, hi in EMB if k in ks], fontsize=6.8, linespacing=1.0)
    a1.set_ylabel('Área da bacia (%)'); a1.set_ylim(0, v.max() * 1.28)
    a1.yaxis.grid(True, linewidth=0.3, color='#c8c8c8', zorder=0)
    for sp in ('top', 'right'): a1.spines[sp].set_visible(False)
    a1.set_title('(a) Classes de declividade (Embrapa)', loc='left', fontsize=8.5, fontweight='bold', pad=6)
    ksh = [k for k, *_ in HIP]; vh = np.array([a_h[k] / tot * 100 for k in ksh])
    los = np.array([lo for _, lo, _ in HIP], float); his = np.array([hi for _, _, hi in HIP], float)
    a2.bar(los, vh, width=25, align='edge', color=[COR_H[k] for k in ksh], edgecolor='black', linewidth=0.5, zorder=3, label='Área por classe')
    for lo, vv in zip(los, vh):
        a2.text(lo + 12.5, vv + 0.6, br(vv), ha='center', va='bottom', fontsize=6.3)
    tk = list(los) + [his[-1]]
    a2.set_xticks(tk); a2.set_xticklabels(['%d' % t for t in tk], fontsize=7)
    a2.set_xlim(los[0], his[-1]); a2.set_xlabel('Altitude (m)'); a2.set_ylabel('Área da bacia (%)')
    a2.set_ylim(0, vh.max() * 1.38); a2.yaxis.grid(True, linewidth=0.3, color='#c8c8c8', zorder=0)
    a2.spines['top'].set_visible(False)
    b2 = a2.twinx(); acc = np.append(100 - np.cumsum(vh) + vh, 0.0)
    b2.plot(tk, acc, color='black', marker='o', ms=2.6, lw=0.9, zorder=4, label='Curva hipsométrica')
    b2.set_ylim(0, 105); b2.set_ylabel('Área acima da cota (%)'); b2.spines['top'].set_visible(False)
    h1, l1 = a2.get_legend_handles_labels(); h2, l2 = b2.get_legend_handles_labels()
    b2.legend(h1 + h2, l1 + l2, frameon=False, fontsize=6.6, loc='center left', bbox_to_anchor=(0.0, 0.58), handlelength=1.6)
    a2.set_title('(b) Distribuição altimétrica e curva hipsométrica', loc='left', fontsize=8.5, fontweight='bold', pad=6)
    a2.text(0.98, 0.97, 'Integral hipsométrica = %s' % br(st['hi'], 2), transform=a2.transAxes, ha='right', va='top', fontsize=6.6)
    fig.subplots_adjust(left=0.075, right=0.925, bottom=0.2, top=0.9)
    GP = os.path.join(FIG, 'Fig_graficos_declividade_hipsometria.png')
    fig.savefig(GP, dpi=500, facecolor='white'); fig.savefig(GP.replace('.png', '.pdf'), facecolor='white'); plt.close(fig)
    log('Exportado gráficos:', GP)

    # ---------- FIGURA DOS MAPAS (dois painéis) ----------
    def fmt(tam, negrito=False):
        f = QgsTextFormat(); fn = QFont(FONTE); fn.setBold(negrito); f.setFont(fn); f.setSize(tam); f.setColor(QColor('#000000'))
        return f
    def rotulo(lay, texto, x, y, w, hgt, tam=7):
        lb = QgsLayoutItemLabel(lay); lb.setText(texto); lb.setTextFormat(fmt(tam)); lb.setMode(QgsLayoutItemLabel.ModeHtml)
        lay.addLayoutItem(lb); lb.attemptMove(QgsLayoutPoint(x, y)); lb.attemptResize(QgsLayoutSize(w, hgt)); return lb

    PW = 168.0; XL = 11.0; MW = 119.0; GAP = 3.0
    CX = XL + MW + GAP
    ext = gb.boundingBox(); ext.grow(200)
    MH = MW * ext.height() / ext.width()
    mgr = proj.layoutManager()
    for l in mgr.printLayouts():
        if l.name() == 'Fig_declividade_hipsometria': mgr.removeLayout(l)
    lay = QgsPrintLayout(proj); lay.initializeDefaults(); lay.setName('Fig_declividade_hipsometria'); mgr.addLayout(lay)
    lay.pageCollection().page(0).setPageSize(QgsLayoutSize(PW, 297))
    S1 = sombra('Sombreamento 12,5 m', 0.40); proj.addMapLayer(S1, False); grp.addLayer(S1)
    S2 = sombra('Sombreamento 12,5 m', 0.55); proj.addMapLayer(S2, False); grp.addLayer(S2)
    VET = [B] + ([R] if R else [])

    def legenda(layer, titulo, x, y):
        lg = QgsLayoutItemLegend(lay); lg.setTitle(titulo); lg.setAutoUpdateModel(False)
        rg = lg.model().rootGroup(); rg.clear()
        nl = rg.addLayer(layer); QgsLegendRenderer.setNodeLegendStyle(nl, QgsLegendStyle.Hidden)
        nos = lg.model().layerLegendNodes(nl)
        QgsMapLayerLegendUtils.setLegendNodeOrder(nl, [i for i, n in enumerate(nos) if not str(n.data(Qt.DisplayRole)).startswith(('Banda', 'Band'))])
        for L, txt in ([(R, 'Rede de drenagem')] if R else []) + [(B, 'Limite da bacia')]:
            n2 = rg.addLayer(L); QgsLegendRenderer.setNodeLegendStyle(n2, QgsLegendStyle.Hidden)
            QgsMapLayerLegendUtils.setLegendNodeUserLabel(n2, 0, txt)
        for n in rg.children(): lg.model().refreshLayerLegend(n)
        lg.rstyle(QgsLegendStyle.Title).setTextFormat(fmt(7, True)); lg.rstyle(QgsLegendStyle.Title).setMargin(QgsLegendStyle.Bottom, 1.2)
        lg.rstyle(QgsLegendStyle.SymbolLabel).setTextFormat(fmt(6.4)); lg.rstyle(QgsLegendStyle.Symbol).setMargin(QgsLegendStyle.Top, 1.0)
        lg.setSymbolWidth(4.2); lg.setSymbolHeight(2.8); lg.setColumnCount(1); lg.setBoxSpace(0)
        lg.setWrapString('|')
        lg.setFrameEnabled(False); lg.setBackgroundEnabled(False)
        lay.addLayoutItem(lg); lg.attemptMove(QgsLayoutPoint(x, y)); lg.adjustBoxSize(); return lg

    def painel(y0, camadas, letra, titulo, leg_layer, leg_titulo):
        m = QgsLayoutItemMap(lay); m.attemptSetSceneRect(QRectF(XL, y0, MW, MH)); m.setCrs(crs)
        m.setLayers(camadas); m.setKeepLayerSet(True); m.setExtent(ext)
        m.setFrameEnabled(True); m.setFrameStrokeWidth(QgsLayoutMeasurement(0.3)); lay.addLayoutItem(m)
        g = QgsLayoutItemMapGrid('UTM', m); g.setCrs(crs); g.setIntervalX(3000); g.setIntervalY(2000)
        g.setStyle(QgsLayoutItemMapGrid.FrameAnnotationsOnly); g.setFrameStyle(QgsLayoutItemMapGrid.ExteriorTicks)
        g.setFrameWidth(1.0); g.setFramePenSize(0.25); g.setAnnotationEnabled(True)
        g.setAnnotationFormat(QgsLayoutItemMapGrid.CustomFormat)
        g.setAnnotationExpression("format_number(@grid_number, 0) || if(@grid_axis = 'x', ' E', ' N')")
        g.setAnnotationTextFormat(fmt(5.8)); g.setAnnotationFrameDistance(0.5)
        for lado in (QgsLayoutItemMapGrid.Top, QgsLayoutItemMapGrid.Right):
            g.setAnnotationDisplay(QgsLayoutItemMapGrid.HideAll, lado)
        g.setAnnotationPosition(QgsLayoutItemMapGrid.OutsideMapFrame, QgsLayoutItemMapGrid.Left)
        g.setAnnotationPosition(QgsLayoutItemMapGrid.OutsideMapFrame, QgsLayoutItemMapGrid.Bottom)
        g.setAnnotationDirection(QgsLayoutItemMapGrid.VerticalDescending, QgsLayoutItemMapGrid.Left)
        m.grids().addGrid(g); m.updateBoundingRect()
        tl = rotulo(lay, '<b>(%s)</b> %s' % (letra, titulo), XL + 0.4, y0 + 0.4, 62 if letra == 'a' else 26, 4.6, 7.2)
        tl.setBackgroundEnabled(True); tl.setBackgroundColor(QColor(255, 255, 255, 225)); tl.setMarginX(0.8); tl.setMarginY(0.4)
        nrt = QgsLayoutItemPicture(lay); nrt.setPicturePath(':/images/north_arrows/layout_default_north_arrow.svg')
        lay.addLayoutItem(nrt); nrt.attemptMove(QgsLayoutPoint(XL + MW - 8.0, y0 + 2.0)); nrt.attemptResize(QgsLayoutSize(5, 7))
        sb = QgsLayoutItemScaleBar(lay); sb.setStyle('Single Box'); sb.setLinkedMap(m); sb.setUnits(QgsUnitTypes.DistanceKilometers)
        sb.setUnitLabel('km'); sb.setNumberOfSegments(2); sb.setNumberOfSegmentsLeft(0); sb.setUnitsPerSegment(1)
        sb.setHeight(1.1); sb.setLineWidth(0.25); sb.setTextFormat(fmt(5.8)); lay.addLayoutItem(sb)
        sb.attemptMove(QgsLayoutPoint(XL + 3.0, y0 + MH - 7.0)); sb.update()
        legenda(leg_layer, leg_titulo, CX, y0 + 0.5)
        return y0 + MH + 5.0

    lay.refresh()
    y1 = painel(2.0, VET + [S1, L_d], 'a', 'Declividade (classes da Embrapa)', L_d, 'Declividade')
    y2 = painel(y1 + 2.0, VET + [S2, L_h], 'b', 'Hipsometria', L_h, 'Altitude')
    qy = y2 + 1.0
    linhas = ['<b>Sistema de referência:</b> WGS 84 / UTM zona 21S (EPSG:32721). <b>Dados:</b> MDE ALOS PALSAR (JAXA/ASF), 12,5 m, '
              'processado com margem de 1 km em torno da bacia; declividade em porcentagem (algoritmo de Horn) reclassificada segundo Embrapa (1979) '
              'e Santos <i>et al.</i> (2018), sem ocorrência da classe escarpado (&gt; 75%); sombreamento multidirecional (exagero vertical de 3×) '
              'sobreposto às classes; hidrografia: Prefeitura Municipal de Foz do Iguaçu. <b>Elaboração:</b> o autor (2026).']
    qw = PW - XL - 2.0; car = int(qw * 1.12)
    qh = sum(math.ceil(len(re.sub('<[^>]+>', '', l)) / car) for l in linhas) * 2.65 + 4.4
    cx = QgsLayoutItemShape(lay); cx.setShapeType(QgsLayoutItemShape.Rectangle)
    cx.setSymbol(QgsFillSymbol.createSimple({'color': '247,247,247,255', 'outline_color': '150,150,150,255', 'outline_width': '0.2'}))
    lay.addLayoutItem(cx); cx.attemptMove(QgsLayoutPoint(XL, qy)); cx.attemptResize(QgsLayoutSize(qw, qh))
    rotulo(lay, '<br>'.join(linhas), XL + 1.2, qy + 0.9, qw - 2.4, qh - 1.2, 5.8)
    lay.pageCollection().page(0).setPageSize(QgsLayoutSize(PW, qy + qh + 2))
    exp = QgsLayoutExporter(lay)
    cfg = QgsLayoutExporter.ImageExportSettings(); cfg.dpi = 500
    dest = os.path.join(FIG, 'Fig_declividade_hipsometria.png')
    r1 = exp.exportToImage(dest, cfg)
    exp.exportToPdf(dest.replace('.png', '.pdf'), QgsLayoutExporter.PdfExportSettings())
    log(('Exportado mapas: ' if r1 == QgsLayoutExporter.Success else 'ERRO export: ') + dest, 'altura', round(qy + qh + 2, 1))
except Exception:
    log(traceback.format_exc())
LOG.close()
