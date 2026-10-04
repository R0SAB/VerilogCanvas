"""Mouse regression for consumed endpoints and deleting one dangling edge."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication,QMessageBox
from PySide6.QtCore import QPointF,Qt
from PySide6.QtTest import QTest
from qt_editor import EditorWindow
from model import route,junction_point
from test_consumed_tips import ConsumedTipTests
app=QApplication([]);w=EditorWindow();w.show();app.processEvents();errors=[]
QMessageBox.warning=lambda parent,title,message,*args:errors.append(str(message))
def setup(doc):
    w.doc=doc;w.history=[];w.future=[];w.rebuild();w.view.set_zoom(1);w.view.centerOn(450,200);app.processEvents()
def point(x,y):return w.view.mapFromScene(QPointF(x,y))
def drag(x,y,offsets):
    QTest.mousePress(w.view.viewport(),Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,point(x,y))
    for dy in offsets:QTest.mouseMove(w.view.viewport(),point(x,y+dy),10);app.processEvents()
    QTest.mouseRelease(w.view.viewport(),Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,point(x,y+offsets[-1]));app.processEvents()
try:
    d,host,left,right=ConsumedTipTests().design();setup(d);before=d.serialize();original_right=route(d,right)
    drag(320,60,[40,80,20,80]);assert route(d,right)==original_right
    drag(600,60,[-40,-100,40,-80]);assert junction_point(d,right)==(400,-20)
    assert junction_point(d,left)==(400,140)
    final=d.serialize();w.undo();w.undo();assert w.doc.serialize()==before
    w.redo();w.redo();assert w.doc.serialize()==final
    d,host,left,right=ConsumedTipTests().design();d.remove_wire(left.id);d.remove_wire(right.id);setup(d);before=d.serialize()
    QTest.mouseClick(w.view.viewport(),Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,point(400,200))
    QTest.keyClick(w.view,Qt.Key.Key_Delete);app.processEvents()
    assert len(w.doc.wires)==1 and route(w.doc,w.doc.wire(host.id))==[(400,460),(800,460)]
    w.undo();assert w.doc.serialize()==before
    w.redo();assert len(w.doc.wires)==1
    assert not errors,errors
    print('Qt consumed tips: independent arms, movement beyond old tip, repeated mouse motion, terminal-segment delete and undo/redo OK')
finally:
    w.drag=None;w.saved=w.doc.serialize();w.close()
