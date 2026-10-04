"""Actual mouse checks for the user's six segment/junction diagrams."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QPointF,Qt
from PySide6.QtWidgets import QApplication,QMessageBox
from PySide6.QtTest import QTest
from qt_editor import EditorWindow,SegmentItem
from model import Node,Port,Document,route,junction_point
from test_segment_graph import SegmentGraphTests

app=QApplication([]);window=EditorWindow();window.show();app.processEvents();errors=[]
def exception(kind,value,tb):
    import traceback
    errors.append(str(value));traceback.print_exception(kind,value,tb)
sys.excepthook=exception
QMessageBox.warning=lambda parent,title,message,*args:errors.append(title+': '+message)

def setup():
    doc,host,branch=SegmentGraphTests().design()
    window.cancel_drawing();window.drag=None;window.doc=doc;window.history=[];window.future=[];window.saved=doc.serialize()
    window.rebuild();window.view.set_zoom(1);window.view.centerOn(200,80);app.processEvents()
    return doc,host,branch

def point(x,y):return window.view.mapFromScene(QPointF(x,y))

try:
    for side,offset,joint in [('left',-60,(240,0)),('left',60,(240,60)),('right',-60,(240,0)),('right',60,(240,60)),('vertical',-180,(60,120)),('vertical',100,(340,0))]:
        doc,host,branch=setup();baseline=doc.serialize();checks=window.net_checks
        x,y=(140,0) if side=='left' else (320,0) if side=='right' else (240,80)
        hit=window.view.itemAt(point(x,y));assert isinstance(hit,SegmentItem),(side,type(hit))
        assert len(window.wire_items['host'].segments)==4  # Junction splits the straight line.
        QTest.mousePress(window.view.viewport(),Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,point(x,y))
        assert window.drag['kind']=='segment',window.drag['kind']
        for delta in (offset,-offset,offset//2,offset):
            px,py=(x+delta,y) if side=='vertical' else (x,y+delta)
            QTest.mouseMove(window.view.viewport(),point(px,py),10);app.processEvents()
            assert window.net_checks==checks
        QTest.mouseRelease(window.view.viewport(),Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,point(px,py));app.processEvents()
        assert junction_point(doc,branch)==joint,(side,offset,junction_point(doc,branch),route(doc,branch))
        assert not window.drag and len(window.history)==1
        container=window.wire_items['branch' if side=='vertical' else 'host']
        assert container.active_segment is not None and container.isSelected()
        final=doc.serialize();window.undo();assert window.doc.serialize()==baseline
        window.redo();assert window.doc.serialize()==final
    # Cursor indicates wiring over an input or output circle, body still indicates movement.
    doc=Document(nodes=[Node(id='n',name='u_test',x=0,y=0,inputs=[Port('d')],outputs=[Port('q')])])
    window.doc=doc;window.rebuild();window.view.centerOn(120,80);app.processEvents()
    for x in (0,240):
        QTest.mouseMove(window.view.viewport(),point(100,20),10);QTest.mouseMove(window.view.viewport(),point(x,60),10);app.processEvents()
        assert window.node_items['n'].cursor().shape()==Qt.CursorShape.ArrowCursor
    assert not errors,errors
    print('Qt segment objects: six mouse scenarios, split at junction, repeated motion, single-segment selection, undo/redo, port cursors OK')
finally:
    window.drag=None;window.saved=window.doc.serialize();window.close()
