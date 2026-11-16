# -*- coding: utf-8 -*-
# =====================================================================
# MAPA DE LOCALIZAÇÃO EM TRÊS PAINÉIS - BACIA DO RIO MATHIAS ALMADA
#   exec(open(r'C:\CAMINHO\PARA\mapa_localizacao.py', encoding='utf-8').read())
# (a) bacia sobre imagem de alta resolução; (b) bacia em Foz do Iguaçu; (c) Foz do Iguaçu no Paraná
# Camadas do projeto: Bacia_H_Rio_Almada, Rios_MA_84, Foz_do_iguacu, Mun_Parana.
# Contexto (países, estados, lagos e rios): Natural Earth 1:10m (domínio público), baixado uma vez para GPKG local.
# =====================================================================
import os, math, re, traceback
import processing
from osgeo import gdal, ogr
from qgis.core import *
from qgis.PyQt.QtGui import QColor, QFont
from qgis.PyQt.QtCore import QRectF, Qt

LOG = open(r'C:\CAMINHO\PARA\DADOS\log_localizacao.txt', 'w', encoding='utf-8')
def log(*a):
    s = ' '.join(str(x) for x in a); print(s); LOG.write(s + '\n'); LOG.flush()
try:
    BASE = r'C:\CAMINHO\PARA\DADOS'
    OUT = os.path.join(BASE, '11_Analise_mudanca_2020_2025')
    FIG = os.path.join(BASE, 'Mapas e Gráficos')
    FONTE = 'Arial'
    proj = QgsProject.instance()
    UTM = QgsCoordinateReferenceSystem('EPSG:32721'); GEO = QgsCoordinateReferenceSystem('EPSG:4674')
    def achar(nome):
        for l in proj.mapLayers().values():
            if l.name() == nome: return l
        raise Exception('Camada não encontrada: ' + nome)
    bacia0 = achar('Bacia_H_Rio_Almada'); rios0 = achar('Rios_MA_84'); foz0 = achar('Foz_do_iguacu'); mun0 = achar('Mun_Parana')

    # ---------- Natural Earth (cache local) ----------
    NE = os.path.join(OUT, 'NaturalEarth_contexto.gpkg')
    URL = '/vsicurl/https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_%s.geojson'
    camadas_ne = {'paises': 'admin_0_countries', 'estados': 'admin_1_states_provinces', 'lagos': 'lakes', 'rios': 'rivers_lake_centerlines'}
    if not os.path.exists(NE):
        for i, (nm, f) in enumerate(camadas_ne.items()):
            gdal.VectorTranslate(NE, URL % f, format='GPKG', layerName=nm, spatFilter=(-62, -32, -42, -17),
                                 accessMode=None if i == 0 else 'update', geometryType='PROMOTE_TO_MULTI', makeValid=True)
            log('Natural Earth baixado:', nm)
    def ne(nm, titulo):
        return QgsVectorLayer(NE + '|layername=' + nm, titulo, 'ogr')

    # ---------- estilos auxiliares ----------
    def fmt(tam, negrito=False, italico=False, cor='#000000'):
        f = QgsTextFormat(); fn = QFont(FONTE); fn.setBold(negrito); fn.setItalic(italico)
        f.setFont(fn); f.setSize(tam); f.setColor(QColor(cor)); return f
    def preench(cor, borda='0,0,0,0', w='0', estilo='solid'):
        return QgsFillSymbol.createSimple({'color': cor, 'style': estilo, 'outline_color': borda, 'outline_width': w, 'outline_style': 'solid' if w != '0' else 'no'})
    def rotular(lay, expr, tam, cor='#555555', italico=True, negrito=False, buf=True, curvo=False, so_pol=True):
        s = QgsPalLayerSettings(); s.fieldName = expr; s.isExpression = True
        tf = fmt(tam, negrito, italico, cor)
        if buf:
            b = QgsTextBufferSettings(); b.setEnabled(True); b.setSize(0.7); b.setColor(QColor(255, 255, 255, 230)); tf.setBuffer(b)
        s.setFormat(tf)
        if curvo: s.placement = Qgis.LabelPlacement.Curved
        elif so_pol: s.placement = Qgis.LabelPlacement.Horizontal
        lay.setLabeling(QgsVectorLayerSimpleLabeling(s)); lay.setLabelsEnabled(True)
    def add(l):
        proj.addMapLayer(l, False); grp.addLayer(l); return l

    nome_grp = 'Figura localização (3 painéis)'
    old = proj.layerTreeRoot().findGroup(nome_grp)
    if old:
        for n in old.findLayers(): proj.removeMapLayer(n.layerId())
        proj.layerTreeRoot().removeChildNode(old)
    grp = proj.layerTreeRoot().insertGroup(0, nome_grp); grp.setItemVisibilityChecked(False)

    # imagem (a)
    esri = add(QgsRasterLayer('type=xyz&url=https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/%7Bz%7D/%7By%7D/%7Bx%7D&zmax=19&zmin=0',
                              'Esri World Imagery', 'wms'))
    log('Esri válido:', esri.isValid())
    # bacia
    bac_lin = add(QgsVectorLayer(bacia0.source(), 'Limite da bacia hidrográfica', 'ogr'))
    sym = QgsFillSymbol()
    sym.deleteSymbolLayer(0)
    for cor, w in (('0,0,0,255', '0.9'), ('255,221,51,255', '0.45')):
        sl = QgsSimpleFillSymbolLayer.create({'style': 'no', 'outline_color': cor, 'outline_width': w}); sym.appendSymbolLayer(sl)
    bac_lin.setRenderer(QgsSingleSymbolRenderer(sym))
    mascara = add(QgsVectorLayer(bacia0.source(), 'Máscara', 'ogr'))
    mascara.setRenderer(QgsInvertedPolygonRenderer(QgsSingleSymbolRenderer(preench('255,255,255,95'))))
    rios_a = add(QgsVectorLayer(rios0.source(), 'Rede de drenagem', 'ogr'))
    rios_a.setRenderer(QgsSingleSymbolRenderer(QgsLineSymbol.createSimple({'line_color': '#56c8ff', 'line_width': '0.32'})))
    bac_fill = add(QgsVectorLayer(bacia0.source(), 'Bacia do rio Mathias Almada', 'ogr'))
    bac_fill.setRenderer(QgsSingleSymbolRenderer(preench('215,48,31,255', '0,0,0,255', '0.25')))
    # municípios
    foz = add(QgsVectorLayer(foz0.source(), 'Foz do Iguaçu', 'ogr'))
    foz.setRenderer(QgsSingleSymbolRenderer(preench('251,236,190,255', '60,60,60,255', '0.35')))
    foz_c = add(QgsVectorLayer(foz0.source(), 'Foz do Iguaçu (c)', 'ogr'))
    foz_c.setRenderer(QgsSingleSymbolRenderer(preench('215,48,31,255', '0,0,0,255', '0.2')))
    mun_b = add(QgsVectorLayer(mun0.source(), 'Municípios do Paraná', 'ogr'))
    mun_b.setRenderer(QgsSingleSymbolRenderer(preench('229,229,229,255', '255,255,255,255', '0.25')))
    mun_c = add(QgsVectorLayer(mun0.source(), 'Municípios do Paraná (c)', 'ogr'))
    mun_c.setRenderer(QgsSingleSymbolRenderer(preench('248,241,222,255', '205,195,170,255', '0.06')))
    # Natural Earth
    pais_b = add(ne('paises', 'Países vizinhos')); pais_b.setRenderer(QgsSingleSymbolRenderer(preench('244,244,244,255', '150,150,150,255', '0.2', 'solid')))
    pais_b2 = add(ne('paises', 'Países (b)')); pais_b2.setRenderer(QgsSingleSymbolRenderer(preench('244,244,244,255')))
    rotular(pais_b2, "CASE WHEN \"ADM0_A3\" IN ('PRY','ARG') THEN upper(\"NAME_PT\") END", 6.5, '#7a7a7a')
    rotular(pais_b, "CASE WHEN \"ADM0_A3\" IN ('PRY','ARG') THEN upper(\"NAME_PT\") END", 6.5, '#7a7a7a')
    pais_c = add(ne('paises', 'Países (c)')); pais_c.setRenderer(QgsSingleSymbolRenderer(preench('244,244,244,255', '150,150,150,255', '0.25')))
    rotular(pais_c, "CASE WHEN \"ADM0_A3\" IN ('PRY','ARG') THEN upper(\"NAME_PT\") END", 6.2, '#7a7a7a')
    est_c = add(ne('estados', 'Estados brasileiros')); est_c.setSubsetString("\"adm0_a3\" = 'BRA'")
    est_c.setRenderer(QgsSingleSymbolRenderer(preench('230,230,230,255', '255,255,255,255', '0.35')))
    rotular(est_c, "CASE WHEN \"postal\" <> 'PR' THEN \"postal\" END", 6.2, '#6b6b6b', italico=False)
    pr_c = processing.run('native:deleteholes', {'INPUT': processing.run('native:dissolve', {'INPUT': mun0, 'FIELD': [], 'OUTPUT': 'memory:'})['OUTPUT'], 'MIN_AREA': 0, 'OUTPUT': 'memory:'})['OUTPUT']; pr_c.setName('Limite do Paraná'); add(pr_c)
    pr_c.setRenderer(QgsSingleSymbolRenderer(preench('0,0,0,0', '40,40,40,255', '0.45', 'no')))
    rotular(pr_c, "'PARANÁ'", 8.0, '#3b3b3b', italico=False, negrito=True)
    lagos = add(ne('lagos', 'Corpos d\'água')); lagos.setRenderer(QgsSingleSymbolRenderer(preench('166,206,227,255', '120,170,205,255', '0.1')))
    rios_ne = add(ne('rios', 'Rios principais')); rios_ne.setRenderer(QgsSingleSymbolRenderer(QgsLineSymbol.createSimple({'line_color': '#5b9bd5', 'line_width': '0.4'})))
    rotular(rios_ne, "'Rio ' || \"name\"", 5.6, '#2c6aa0', curvo=True)
    oceano = QgsVectorLayer('Point?crs=EPSG:4674&field=t:string', 'Rótulos', 'memory')
    ft = QgsFeature(oceano.fields()); ft.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(-48.25, -26.35))); ft['t'] = 'OCEANO\nATLÂNTICO'
    oceano.dataProvider().addFeatures([ft]); add(oceano)
    oceano.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple({'size': '0', 'color': '0,0,0,0', 'outline_style': 'no'})))
    rotular(oceano, '"t"', 6.0, '#3f6e94', buf=False, so_pol=False)

    # ---------- extensões ----------
    def bbox(layer, crs, grow):
        tr = QgsCoordinateTransform(layer.crs(), crs, proj)
        e = tr.transformBoundingBox(layer.extent()); e.grow(grow); return e
    ea = bbox(bacia0, UTM, 300)
    eb = bbox(foz0, UTM, 3500)
    ec = bbox(mun0, GEO, 0.35)
    def ajusta(e, w, h):  # expande e para a proporção w/h do quadro
        r = w / h
        if e.width() / e.height() > r:
            d = e.width() / r - e.height(); e.setYMinimum(e.yMinimum() - d / 2); e.setYMaximum(e.yMaximum() + d / 2)
        else:
            d = e.height() * r - e.width(); e.setXMinimum(e.xMinimum() - d / 2); e.setXMaximum(e.xMaximum() + d / 2)
        return e

    PW = 168.0; XL = 11.0; MW = PW - XL - 4.0; GAP = 9.0
    MHa = MW * ea.height() / ea.width()
    rb = eb.width() / eb.height(); rc = ec.width() / ec.height()
    H2 = (MW - GAP) / (rb + rc)
    WB = H2 * rb; WC = H2 * rc
    mgr = proj.layoutManager()
    for l in mgr.printLayouts():
        if l.name() == 'Fig_localizacao_3paineis': mgr.removeLayout(l)
    lay = QgsPrintLayout(proj); lay.initializeDefaults(); lay.setName('Fig_localizacao_3paineis'); mgr.addLayout(lay)
    lay.pageCollection().page(0).setPageSize(QgsLayoutSize(PW, 297))

    def rotulo(texto, x, y, w, h, tam=7, fundo=False):
        lb = QgsLayoutItemLabel(lay); lb.setText(texto); lb.setTextFormat(fmt(tam)); lb.setMode(QgsLayoutItemLabel.ModeHtml)
        lay.addLayoutItem(lb); lb.attemptMove(QgsLayoutPoint(x, y)); lb.attemptResize(QgsLayoutSize(w, h))
        if fundo:
            lb.setBackgroundEnabled(True); lb.setBackgroundColor(QColor(255, 255, 255, 230)); lb.setMarginX(0.8); lb.setMarginY(0.4)
        return lb

    def mapa(x, y, w, h, crs, ext, camadas, fundo='#ffffff'):
        m = QgsLayoutItemMap(lay); m.attemptSetSceneRect(QRectF(x, y, w, h)); m.setCrs(crs)
        m.setLayers(camadas); m.setKeepLayerSet(True); m.setExtent(ajusta(ext, w, h))
        m.setBackgroundColor(QColor(fundo)); m.setFrameEnabled(True); m.setFrameStrokeWidth(QgsLayoutMeasurement(0.3))
        lay.addLayoutItem(m); return m

    def grade(m, crs, ix, iy, expr, tam=5.5, lados=('L', 'B')):
        g = QgsLayoutItemMapGrid('grade', m); g.setCrs(crs); g.setIntervalX(ix); g.setIntervalY(iy)
        g.setStyle(QgsLayoutItemMapGrid.FrameAnnotationsOnly); g.setFrameStyle(QgsLayoutItemMapGrid.ExteriorTicks)
        g.setFrameWidth(1.0); g.setFramePenSize(0.25); g.setAnnotationEnabled(True)
        g.setAnnotationFormat(QgsLayoutItemMapGrid.CustomFormat); g.setAnnotationExpression(expr)
        g.setAnnotationTextFormat(fmt(tam)); g.setAnnotationFrameDistance(0.5)
        for lado in (QgsLayoutItemMapGrid.Top, QgsLayoutItemMapGrid.Right):
            g.setAnnotationDisplay(QgsLayoutItemMapGrid.HideAll, lado)
        g.setAnnotationPosition(QgsLayoutItemMapGrid.OutsideMapFrame, QgsLayoutItemMapGrid.Left)
        g.setAnnotationPosition(QgsLayoutItemMapGrid.OutsideMapFrame, QgsLayoutItemMapGrid.Bottom)
        g.setAnnotationDirection(QgsLayoutItemMapGrid.VerticalDescending, QgsLayoutItemMapGrid.Left)
        m.grids().addGrid(g); m.updateBoundingRect()

    def norte(x, y, s=5):
        n = QgsLayoutItemPicture(lay); n.setPicturePath(':/images/north_arrows/layout_default_north_arrow.svg')
        lay.addLayoutItem(n); n.attemptMove(QgsLayoutPoint(x, y)); n.attemptResize(QgsLayoutSize(s * 0.7, s))

    def escala(m, x, y, seg, n=2, cor_txt='#000000', fundo=False):
        sb = QgsLayoutItemScaleBar(lay); sb.setStyle('Single Box'); sb.setLinkedMap(m); sb.setUnits(QgsUnitTypes.DistanceKilometers)
        sb.setUnitLabel('km'); sb.setNumberOfSegments(n); sb.setNumberOfSegmentsLeft(0); sb.setUnitsPerSegment(seg)
        sb.setHeight(1.0); sb.setLineWidth(0.25); sb.setTextFormat(fmt(5.5, cor=cor_txt))
        sb.setBoxContentSpace(0.7)
        if fundo:
            sb.setBackgroundEnabled(True); sb.setBackgroundColor(QColor(255, 255, 255, 215))
        lay.addLayoutItem(sb); sb.attemptMove(QgsLayoutPoint(x, y)); sb.update()
        sb.resizeToMinimumWidth(); ms = sb.minimumSize(); sb.attemptResize(QgsLayoutSize(ms.width(), ms.height())); sb.update(); return sb

    UTMX = "format_number(@grid_number, 0) || if(@grid_axis = 'x', ' E', ' N')"
    GEOX = "to_string(abs(@grid_number)) || '°' || if(@grid_axis = 'x', if(@grid_number < 0, ' O', ' L'), if(@grid_number < 0, ' S', ' N'))"
    lay.refresh()
    # (a)
    ya = 2.0
    ma = mapa(XL, ya, MW, MHa, UTM, ea, [bac_lin, rios_a, mascara, esri])
    grade(ma, UTM, 3000, 2000, UTMX)
    rotulo('<b>(a)</b> Bacia hidrográfica do rio Mathias Almada', XL + 0.4, ya + 0.4, 66, 4.6, 7.2, True)
    norte(XL + MW - 7.5, ya + 2.0, 7)
    escala(ma, XL + 1.5, ya + MHa - 8.6, 1, 2, fundo=True)
    # (b) e (c)
    yb = ya + MHa + 6.0
    mb = mapa(XL, yb, WB, H2, UTM, eb, [bac_fill, foz, mun_b, pais_b2], '#f4f4f4')
    grade(mb, UTM, 20000, 20000, UTMX, 5.2)
    rotulo('<b>(b)</b> Foz do Iguaçu', XL + 0.4, yb + 0.4, 24, 4.4, 7, True)
    norte(XL + WB - 5.6, yb + 1.6, 5.5)
    escala(mb, XL + 1.5, yb + H2 - 8.6, 5, 2, fundo=True)
    xc = XL + WB + GAP
    mc = mapa(xc, yb, WC, H2, GEO, ec, [oceano, foz_c, pr_c, rios_ne, mun_c, lagos, est_c, pais_c], '#dbe9f4')
    grade(mc, GEO, 2, 1, GEOX, 5.2)
    rotulo('<b>(c)</b> Paraná', xc + 0.4, yb + 0.4, 18, 4.4, 7, True)
    norte(xc + WC - 5.6, yb + 1.6, 5.5)
    escala(mc, xc + WC * 0.40, yb + H2 - 8.6, 50, 2, fundo=True)
    # quadros de localização (extensão do painel anterior)
    def quadro(m_dest, m_orig):
        ov = QgsLayoutItemMapOverview('ext', m_dest); ov.setLinkedMap(m_orig)
        ov.setFrameSymbol(preench('0,0,0,0', '200,0,0,255', '0.45', 'no')); m_dest.overviews().addOverview(ov)
    quadro(mb, ma); quadro(mc, mb)

    # ---------- legenda comum ----------
    yl = yb + H2 + 6.0
    lg = QgsLayoutItemLegend(lay); lg.setTitle(''); lg.setAutoUpdateModel(False)
    rg = lg.model().rootGroup(); rg.clear()
    itens = [(bac_lin, 'Limite da bacia (a)'), (bac_fill, 'Bacia (b)'), (rios_a, 'Rede de drenagem (a)'),
             (foz, 'Foz do Iguaçu (b)'), (foz_c, 'Foz do Iguaçu (c)'), (pr_c, 'Limite estadual do Paraná (c)'),
             (mun_b, 'Outros municípios do Paraná'), (est_c, 'Outros estados brasileiros'), (pais_b, 'Países vizinhos'),
             (rios_ne, 'Rios principais (c)'), (lagos, 'Reservatórios e lagos (c)')]
    for L, txt in itens:
        n = rg.addLayer(L); QgsLegendRenderer.setNodeLegendStyle(n, QgsLegendStyle.Hidden)
        QgsMapLayerLegendUtils.setLegendNodeUserLabel(n, 0, txt)
    for n in rg.children(): lg.model().refreshLayerLegend(n)
    lg.rstyle(QgsLegendStyle.SymbolLabel).setTextFormat(fmt(6.2)); lg.rstyle(QgsLegendStyle.Symbol).setMargin(QgsLegendStyle.Top, 0.9)
    lg.setSymbolWidth(4.2); lg.setSymbolHeight(2.8); lg.setColumnCount(4); lg.setSplitLayer(True); lg.setEqualColumnWidth(True)
    lg.setColumnSpace(4); lg.setBoxSpace(0); lg.setFrameEnabled(False); lg.setBackgroundEnabled(False)
    lay.addLayoutItem(lg); lg.attemptMove(QgsLayoutPoint(XL, yl)); lg.attemptResize(QgsLayoutSize(MW, 14)); lg.adjustBoxSize()
    hq = math.ceil(len(itens) / 4.0) * 3.75 + 0.5
    qy = yl + hq + 3.0
    linhas = ['<b>Sistemas de referência:</b> (a) e (b) WGS 84 / UTM zona 21S (EPSG:32721); (c) SIRGAS 2000, coordenadas geográficas (EPSG:4674). '
              'Os retângulos vermelhos em (b) e (c) indicam a área representada no painel anterior. <b>Dados:</b> limite da bacia: elaborado pelo autor; rede de drenagem: '
              'Prefeitura Municipal de Foz do Iguaçu; limites municipais: IBGE; países, estados, rios principais e reservatórios: Natural Earth (1:10.000.000); '
              'imagem em (a): Esri World Imagery (Esri, Maxar, Earthstar Geographics). <b>Elaboração:</b> o autor (2026).']
    qw = MW; car = int(qw * 1.12)
    qh = sum(math.ceil(len(re.sub('<[^>]+>', '', l)) / car) for l in linhas) * 2.65 + 2.4
    cx = QgsLayoutItemShape(lay); cx.setShapeType(QgsLayoutItemShape.Rectangle)
    cx.setSymbol(preench('247,247,247,255', '150,150,150,255', '0.2')); lay.addLayoutItem(cx)
    cx.attemptMove(QgsLayoutPoint(XL, qy)); cx.attemptResize(QgsLayoutSize(qw, qh))
    rotulo('<br>'.join(linhas), XL + 1.2, qy + 0.9, qw - 2.4, qh - 1.2, 5.8)
    lay.pageCollection().page(0).setPageSize(QgsLayoutSize(PW, qy + qh + 2))
    exp = QgsLayoutExporter(lay)
    cfg = QgsLayoutExporter.ImageExportSettings(); cfg.dpi = 400
    dest = os.path.join(FIG, 'Fig_localizacao_3paineis.png')
    r1 = exp.exportToImage(dest, cfg)
    exp.exportToPdf(dest.replace('.png', '.pdf'), QgsLayoutExporter.PdfExportSettings())
    log(('Exportado: ' if r1 == QgsLayoutExporter.Success else 'ERRO export: ') + dest, 'tamanho %.1f x %.1f mm' % (PW, qy + qh + 2),
        'painéis: a %.1fx%.1f, b %.1fx%.1f, c %.1fx%.1f' % (MW, MHa, WB, H2, WC, H2))
except Exception:
    log(traceback.format_exc())
LOG.close()
