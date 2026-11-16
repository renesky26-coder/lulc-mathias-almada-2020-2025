# -*- coding: utf-8 -*-
# =====================================================================
# RECÁLCULO DO HAND SEM EFEITO DE BORDA (MDE com margem de 3 km)
#   exec(open(r'C:\CAMINHO\PARA\hand_recalculo.py', encoding='utf-8').read())
# Etapas (seção 4.2.6): preenchimento de depressões (priority-flood) -> direção de
# fluxo D8 -> acúmulo de fluxo -> rede de drenagem (>= 1.000 células) -> HAND.
# Saídas em 11_Analise_mudanca_2020_2025: HAND_m_12m.tif, Drenagem_HAND_12m.tif
# =====================================================================
import os, heapq, time
import numpy as np
from osgeo import gdal
from qgis.core import QgsProject, QgsVectorLayer, QgsWkbTypes, QgsCoordinateTransform, QgsCoordinateReferenceSystem

DEM = r'C:\CAMINHO\PARA\MDE_12m.tif'
BASE = r'C:\CAMINHO\PARA\DADOS'
OUT = os.path.join(BASE, '11_Analise_mudanca_2020_2025')
RES, MARGEM, LIMIAR = 12.5, 3000.0, 1000
t0 = time.time()
proj = QgsProject.instance()
bacia = [l for l in proj.mapLayers().values() if isinstance(l, QgsVectorLayer)
         and l.geometryType() == QgsWkbTypes.PolygonGeometry and 'bacia' in l.name().lower()][0]
tr = QgsCoordinateTransform(bacia.crs(), QgsCoordinateReferenceSystem('EPSG:32721'), proj)
e = tr.transformBoundingBox(bacia.extent())
xmin = np.floor((e.xMinimum() - MARGEM) / RES) * RES; xmax = np.ceil((e.xMaximum() + MARGEM) / RES) * RES
ymin = np.floor((e.yMinimum() - MARGEM) / RES) * RES; ymax = np.ceil((e.yMaximum() + MARGEM) / RES) * RES
ds = gdal.Warp('', DEM, format='MEM', dstSRS='EPSG:32721', outputBounds=(xmin, ymin, xmax, ymax),
               xRes=RES, yRes=RES, resampleAlg='bilinear', dstNodata=-9999)
z = ds.GetRasterBand(1).ReadAsArray().astype(np.float64)
gt, prj = ds.GetGeoTransform(), ds.GetProjection()
ny, nx = z.shape
nodata = (z <= -9000) | ~np.isfinite(z)
print('MDE recortado: %d x %d células (%.1f x %.1f km); nodata = %d' % (nx, ny, nx * RES / 1000, ny * RES / 1000, nodata.sum()))

# 1) preenchimento de depressões (priority-flood com epsilon; Barnes et al., 2014)
N = nx * ny
zf = z.ravel().copy()
nd = nodata.ravel()
vis = np.zeros(N, bool)
heap = []
borda = np.zeros((ny, nx), bool); borda[0, :] = borda[-1, :] = borda[:, 0] = borda[:, -1] = True
borda = borda.ravel() | (nd & False)
for i in np.flatnonzero(borda & ~nd):
    heap.append((zf[i], int(i))); vis[i] = True
vis[nd] = True
heapq.heapify(heap)
OFF = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
zl = zf.tolist(); visl = vis.tolist()
EPS = 1e-4
push, pop = heapq.heappush, heapq.heappop
while heap:
    h, i = pop(heap)
    r, c = divmod(i, nx)
    for dr, dc in OFF:
        rr, cc = r + dr, c + dc
        if 0 <= rr < ny and 0 <= cc < nx:
            j = rr * nx + cc
            if not visl[j]:
                visl[j] = True
                if zl[j] <= h:
                    zl[j] = h + EPS
                push(heap, (zl[j], j))
zf = np.array(zl).reshape(ny, nx)
zf[nodata] = np.nan
print('1) Depressões preenchidas: %.0f s' % (time.time() - t0))

# 2) direção de fluxo D8 (maior declividade)
pad = np.pad(zf, 1, constant_values=np.nan)
best = np.full((ny, nx), -np.inf); down = np.full((ny, nx), -1, np.int64)
rows, cols = np.indices((ny, nx))
for k, (dr, dc) in enumerate(OFF):
    nb = pad[1 + dr:1 + dr + ny, 1 + dc:1 + dc + nx]
    s = (zf - nb) / (RES * (2 ** 0.5 if dr and dc else 1))
    s = np.where(np.isfinite(s), s, -np.inf)
    m = s > best
    best[m] = s[m]
    tgt = (rows + dr) * nx + (cols + dc)
    down[m] = tgt[m]
down[(best <= 0) | nodata] = -1
print('2) Direção de fluxo: %.0f s' % (time.time() - t0))

# 3) acúmulo de fluxo (células a montante, incluindo a própria)
fl = zf.ravel(); dl = down.ravel()
ordem = np.argsort(np.where(np.isfinite(fl), fl, -np.inf))[::-1]
acc = np.where(nodata.ravel(), 0, 1).astype(np.int64)
accl = acc.tolist(); dll = dl.tolist()
for i in ordem.tolist():
    d = dll[i]
    if d >= 0:
        accl[d] += accl[i]
acc = np.array(accl)
print('3) Acúmulo de fluxo: %.0f s' % (time.time() - t0))

# 4) rede de drenagem
rede = acc >= LIMIAR
# 5) HAND: desnível entre a célula e a célula de drenagem para onde ela escoa
ref = fl.copy(); refl = ref.tolist(); fll = fl.tolist(); redel = rede.tolist()
for i in ordem[::-1].tolist():
    d = dll[i]
    if not redel[i] and d >= 0:
        refl[i] = refl[d]
hand = (fl - np.array(refl)).reshape(ny, nx)
hand[nodata] = np.nan
print('4-5) Rede (%d células) e HAND: %.0f s' % (rede.sum(), time.time() - t0))

def salvar(path, arr, tipo, ndv):
    if os.path.exists(path):
        for l in proj.mapLayers().values():
            if l.source().replace('/', '\\').lower() == path.lower():
                proj.removeMapLayer(l.id())
        try: os.remove(path)
        except OSError: pass
    o = gdal.GetDriverByName('GTiff').Create(path, nx, ny, 1, tipo, ['COMPRESS=LZW'])
    o.SetGeoTransform(gt); o.SetProjection(prj)
    b = o.GetRasterBand(1); b.WriteArray(arr); b.SetNoDataValue(ndv); o = None

HAND_TIF = os.path.join(OUT, 'HAND_m_12m.tif')
salvar(HAND_TIF, np.where(np.isfinite(hand), hand, -9999).astype(np.float32), gdal.GDT_Float32, -9999)
salvar(os.path.join(OUT, 'Drenagem_HAND_12m.tif'), rede.reshape(ny, nx).astype(np.uint8), gdal.GDT_Byte, 0)
print('HAND salvo:', HAND_TIF, '| tempo total %.0f s' % (time.time() - t0))
