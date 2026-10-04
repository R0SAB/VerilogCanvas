"""Grid alignment, caching and view-only state regression; requires PySide6."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication
from qt_app import Window,BG
app=QApplication([]);w=Window();w.resize(1000,700);w.show();app.processEvents()
try:
    state=w.doc.serialize();checks=w.net_checks
    for zoom in (1,.73,2,.1):
        w.view.set_zoom(zoom);w.view.centerOn(0,0);app.processEvents()
        w.view.viewport().repaint();brush=w.view.dot_brush();builds=w.view.grid_tile_builds
        for x in (13,27,-31,0):
            w.view.centerOn(x,0);app.processEvents();w.view.viewport().repaint()
            assert w.view.grid_tile_builds==builds
        if zoom>=.73:
            image=w.view.viewport().grab().toImage();dpr=image.devicePixelRatio()
            for point in ((0,0),(100,100),(-100,-100)):
                pixel=w.view.mapFromScene(QPointF(*point));px=round(pixel.x()*dpr);py=round(pixel.y()*dpr)
                assert any(image.pixelColor(x,y)!=QColor(BG) for x in range(px-2,px+3) for y in range(py-2,py+3)),(zoom,point)
    w.grid_choice.setCurrentText('Off');app.processEvents();image=w.view.viewport().grab().toImage()
    assert image.pixelColor(image.width()//2,image.height()//2)==QColor(BG)
    w.grid_choice.setCurrentText('Lines');app.processEvents();w.grid_choice.setCurrentText('Dots');app.processEvents()
    assert w.doc.serialize()==state and w.net_checks==checks
    assert len(w.view.grid_tiles)<=8
    print('Grid: world alignment, negative coordinates, fractional zoom, tile reuse during pan, Off/Lines/Dots, unchanged schematic OK')
finally:w.saved=w.doc.serialize();w.close()
