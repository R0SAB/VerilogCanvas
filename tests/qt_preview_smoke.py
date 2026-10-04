"""Run with QT_QPA_PLATFORM=offscreen; requires PySide6, no Tk dependency."""
import copy
import statistics
import sys
import tempfile
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog
from model import Document, Node, Port, TextComment, route
from qt_app import Window

app=QApplication([]);window=Window();window.show();app.processEvents();errors=[]
def exception(kind,value,tb):
    import traceback
    errors.append(str(value));traceback.print_exception(kind,value,tb)
sys.excepthook=exception

def setup(doc):
    window.drag=None;window.doc=doc;window.saved=doc.serialize();window.history=[];window.future=[]
    window.rebuild();window.fit();app.processEvents()

try:
    # Open every supplied example, including raw-text inline sources and SV.
    for path in sorted((Path(__file__).resolve().parents[1]/'examples').glob('*.vsch')):
        assert window.load(path),path
        loaded=window.doc.serialize()
        app.processEvents();window.view.viewport().repaint()
        assert window.doc.serialize()==loaded,path

    a=Node(id='a',name='driver',x=0,y=0,inputs=[],outputs=[Port('q','7:0')])
    b=Node(id='b',name='receiver',x=600,y=200,inputs=[Port('d','7:0')],outputs=[])
    doc=Document(nodes=[a,b]);wire=doc.connect(('a','q'),('b','d'));label=doc.label_wire(wire.id,'bus')
    setup(doc);baseline=doc.serialize();hdl=doc.verilog();checks=window.net_checks
    identities={id(item) for item in window.scene.items()}
    item=window.node_items['b'];origin=QPointF(b.x+80,b.y+20)
    window.begin_drag(item,origin,Qt.KeyboardModifier.NoModifier)
    for offset in (20,40,60):window.move_drag(origin+QPointF(offset,offset));app.processEvents()
    assert window.net_checks==checks
    assert {id(i) for i in window.scene.items()}==identities
    window.finish_drag();assert doc.verilog()==hdl
    assert doc.node('b').x==660 and doc.node('b').y==260
    window.undo();assert window.doc.serialize()==baseline
    window.redo();assert window.doc.node('b').x==660
    state=window.doc.serialize();item=window.node_items['b']
    window.begin_drag(item,QPointF(700,280),Qt.KeyboardModifier.NoModifier)
    window.move_drag(QPointF(800,380));window.cancel_drag();assert window.doc.serialize()==state

    # Real mouse events reach the retained object and update the model.
    window.view.set_zoom(1);window.view.centerOn(500,180);app.processEvents()
    start=window.view.mapFromScene(QPointF(720,278));end=start+window.view.mapFromScene(QPointF(40,40))-window.view.mapFromScene(QPointF(0,0))
    QTest.mousePress(window.view.viewport(),Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,start)
    QTest.mouseMove(window.view.viewport(),end,10)
    QTest.mouseRelease(window.view.viewport(),Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,end)
    app.processEvents();assert window.doc.node('b').x==700

    # Navigation does not check nets, change model geometry or rebuild items.
    state=window.doc.serialize();checks=window.net_checks;identities={id(i) for i in window.scene.items()}
    for z in (.4,1,2,.7):
        window.view.set_zoom(z);window.view.centerOn(600+z*50,200);app.processEvents()
    assert window.net_checks==checks and window.doc.serialize()==state
    assert {id(i) for i in window.scene.items()}==identities

    with tempfile.TemporaryDirectory() as tmp:
        target=Path(tmp)/'copy.vsch';old=QFileDialog.getSaveFileName
        QFileDialog.getSaveFileName=lambda *args,**kwargs:(str(target),'')
        try:window.save_copy()
        finally:QFileDialog.getSaveFileName=old
        assert Document.load(target).serialize()==window.doc.serialize()
        assert Document.load(target).verilog()==hdl

    # Physical groups move together; Ctrl moves just the chosen member.
    doc=Document.deserialize(baseline);doc.comments=[TextComment(id='g',kind='group',text='Group caption wraps inside the frame',x=-40,y=-40,w=1000,h=500)]
    setup(doc);window.begin_drag(window.node_items['a'],QPointF(60,20),Qt.KeyboardModifier.NoModifier)
    window.move_drag(QPointF(100,60));window.finish_drag()
    assert doc.node('a').x==40 and doc.node('b').x==640 and doc.comments[0].x==0
    window.scene.clearSelection();window.begin_drag(window.node_items['a'],QPointF(100,60),Qt.KeyboardModifier.ControlModifier)
    window.move_drag(QPointF(120,80));window.finish_drag();assert doc.node('a').x==60 and doc.node('b').x==640

    # Detached geometry and label move as a unit. End and segment drags also work.
    doc=Document.deserialize(baseline);doc.remove_node('a');doc.remove_node('b');setup(doc)
    wi=window.wire_items[wire.id];before=route(doc,wi.w);origin=QPointF(*before[1])
    window.begin_drag(wi,origin,Qt.KeyboardModifier.NoModifier);window.move_drag(origin+QPointF(80,60));window.finish_drag()
    assert route(doc,wi.w)==[(x+80,y+60) for x,y in before]
    wi=window.wire_items[wire.id];point=wi.w.loose_ends()[0][1]
    window.begin_drag(wi,QPointF(*point),Qt.KeyboardModifier.NoModifier);window.move_drag(QPointF(point[0]+40,point[1]+20));window.finish_drag()
    assert wi.w.loose_ends()[0][1]==[point[0]+40,point[1]+20]

    if len(sys.argv)>1:
        assert window.load(sys.argv[1]);app.processEvents();checks=window.net_checks
        node=next(n for n in window.doc.nodes if n.kind=='module')
        window.view.set_zoom(1);window.view.centerOn(node.x+node.w/2,node.y+node.h/2);app.processEvents()
        origin=QPointF(node.x+60,node.y+20);window.begin_drag(window.node_items[node.id],origin,Qt.KeyboardModifier.ControlModifier)
        timings=[]
        for frame in range(100):
            start=time.perf_counter();window.move_drag(origin+QPointF(frame%10*20,frame%5*20))
            window.view.viewport().repaint();app.processEvents();timings.append((time.perf_counter()-start)*1000)
        assert window.net_checks==checks;window.cancel_drag()
        print(f'Supplied schematic: {len(window.doc.nodes)} nodes, {len(window.doc.wires)} wires; offscreen move+paint mean {statistics.mean(timings):.2f} ms, p95 {sorted(timings)[94]:.2f} ms')
    assert not errors,errors
    print('Qt smoke: examples, retained items, real mouse drag, no net checks during movement/navigation, groups/Ctrl, free ends, undo/redo/Esc, save-copy HDL equivalence OK')
finally:
    window.drag=None;window.saved=window.doc.serialize();window.close()
