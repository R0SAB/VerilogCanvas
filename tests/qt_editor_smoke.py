"""Qt editor interaction and file-workflow regression checks (offscreen safe)."""
import copy
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QInputDialog
from PySide6.QtGui import QImage
from qt_editor import EditorWindow
from qt_dialogs import EditorDialog, InlineDialog, CommentDialog, DeclarationsDialog
from model import Document, Node, Port, TextComment, route, junction_point

app=QApplication([]);w=EditorWindow();w.show();app.processEvents();errors=[]
def exception(kind,value,tb):
    import traceback
    errors.append(str(value));traceback.print_exception(kind,value,tb)
sys.excepthook=exception
old_warning=QMessageBox.warning
QMessageBox.warning=lambda parent,title,message,*args:errors.append(title+': '+message)

def setup(doc):
    w.cancel_drawing();w.drag=None;w.doc=doc;w.saved=doc.serialize();w.history=[];w.future=[];w.path=None
    w.rebuild();w.update_title();w.view.set_zoom(1);w.view.centerOn(500,200);app.processEvents()

def click(x,y):
    QTest.mouseClick(w.view.viewport(),Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,w.view.mapFromScene(QPointF(x,y)));app.processEvents()

def drag(start,end,mods=Qt.KeyboardModifier.NoModifier):
    a=w.view.mapFromScene(QPointF(*start));b=w.view.mapFromScene(QPointF(*end))
    QTest.mousePress(w.view.viewport(),Qt.MouseButton.LeftButton,mods,a)
    QTest.mouseMove(w.view.viewport(),b,10)
    QTest.mouseRelease(w.view.viewport(),Qt.MouseButton.LeftButton,mods,b);app.processEvents()

try:
    a=Node(id='a',name='driver',module='source',x=0,y=0,inputs=[],outputs=[Port('q','7:0')])
    b=Node(id='b',name='receiver',module='sink',x=600,y=200,inputs=[Port('d','7:0')],outputs=[])
    setup(Document(nodes=[a,b]))
    # Actual port clicks create the exact route shown in the preview.
    click(240,60);assert w.pending==('a','q')
    click(400,60);click(400,260);w.preview_wire(QPointF(600,260))
    path=w.preview_item.path();expected=[(path.elementAt(i).x,path.elementAt(i).y) for i in range(path.elementCount())]
    click(600,260);assert w.pending is None and len(w.doc.wires)==1
    wire=w.doc.wires[0];assert route(w.doc,wire)==expected,(route(w.doc,wire),expected)
    # Branches land on real junctions, can move, and survive removing their host.
    c=Node(id='c',name='receiver2',module='sink',x=600,y=-160,inputs=[Port('d','7:0')],outputs=[])
    w.apply(lambda doc:doc.nodes.append(c));click(600,-100)
    near=w.nearest_wire(QPointF(320,60));w.commit_wire(join_wire=near[0],join_position=near[1])
    branch=w.doc.wires[-1];assert branch.join_wire==wire.id and branch.join_vertex
    joint=junction_point(w.doc,branch);item=w.wire_items[branch.id]
    w.begin_drag(item,QPointF(*joint),Qt.KeyboardModifier.NoModifier);assert w.drag['kind']=='junction'
    w.move_drag(QPointF(360,60));w.finish_drag();assert junction_point(w.doc,branch)==(360,60)
    # Label capture works even far away from the wire; it can transfer wires.
    label=w.apply(lambda doc:doc.label_wire(wire.id,'data_bus',.2))
    item=w.label_items[label.id];origin=item.pos()+QPointF(20,-20)
    w.begin_drag(item,origin,Qt.KeyboardModifier.NoModifier);w.move_drag(origin+QPointF(100,180));w.finish_drag()
    assert next(l for l in w.doc.labels if l.id==label.id).position!=.2
    # Module resize uses real corner events, retains scene objects during motion.
    item=w.node_items['b'];before=w.doc.node('b').w;count=w.net_checks
    start=(840,360);end=(900,400);drag(start,end)
    assert w.doc.node('b').w==before+60 and w.net_checks==count+1
    # Deleting modules retains wires, geometry and labels; replacement reattaches.
    baseline=w.doc.serialize();endpoint=w.doc.node('a').endpoint('q');old_route=route(w.doc,w.doc.wire(wire.id))
    w.select('node','a');w.delete();assert len(w.doc.wires)==2 and w.doc.labels
    assert route(w.doc,w.doc.wire(wire.id))==old_route
    replacement=copy.deepcopy(a);replacement.id='new';replacement.name='new_driver'
    def replace(doc):doc.nodes.append(replacement);doc.attach_coincident(node_ids={'new'})
    w.apply(replace);assert w.doc.wire(wire.id).source==('new','q')
    w.undo();assert not any(n.id=='new' for n in w.doc.nodes);w.undo();assert w.doc.serialize()==baseline
    # Width errors complete the operation, appear in diagnostics and are undoable.
    bad=Node(id='bad',name='bad_sink',x=1000,y=400,inputs=[Port('d')],outputs=[])
    w.apply(lambda doc:doc.nodes.append(bad));w.start_wire(('a','q'));w.commit_wire(second=('bad','d'))
    assert ('bad','d') in w.bad_ports;assert w.doc.wires[-1].id in w.bad_wires
    w.undo();w.undo();assert w.doc.serialize()==baseline
    # Group includes I/O and comments, copy renames ports and instances.
    port=Node(id='in',kind='input',name='clk',x=40,y=240,inputs=[],outputs=[Port('clk')]);port.normalize()
    group=TextComment(id='g',kind='group',text='A long group heading that wraps across several lines',x=-40,y=-40,w=1000,h=600)
    note=TextComment(id='note',text='Notes',x=300,y=340,w=200,h=60)
    setup(Document(nodes=[a,b,port],comments=[group,note]))
    w.select('node','a');w.copy_selection();w.paste();assert len(w.doc.nodes)==6 and len(w.doc.comments)==4
    assert len({n.name for n in w.doc.nodes})==6
    w.undo();w.select('node','a');start=QPointF(80,20);checks=w.net_checks;identities={id(i) for i in w.scene.items()}
    w.begin_drag(w.node_items['a'],start,Qt.KeyboardModifier.NoModifier);w.move_drag(start+QPointF(40,40))
    assert w.doc.node('in').x==80 and w.doc.comment('note').x==340 and w.net_checks==checks
    assert {id(i) for i in w.scene.items()}==identities
    w.finish_drag();w.begin_drag(w.node_items['a'],start+QPointF(40,40),Qt.KeyboardModifier.ControlModifier);w.move_drag(start+QPointF(60,60));w.finish_drag();assert w.doc.node('in').x==80
    # Comment resize, selection marker, cancellation.
    w.select('comment','note');c=w.doc.comment('note');item=w.comment_items['note'];before=w.doc.serialize()
    start=QPointF(c.x+c.w,c.y+item.height);w.begin_drag(item,start,Qt.KeyboardModifier.NoModifier);assert w.drag['kind']=='resize'
    w.move_drag(start+QPointF(100,40));assert c.w==300;w.cancel_drag();assert w.doc.serialize()==before
    # A group has an active resize grip without prior selection; its contents stay put.
    setup(Document(nodes=[copy.deepcopy(a)],comments=[TextComment(id='g',kind='group',text='Group',x=-40,y=-40,w=400,h=240)]))
    original=w.doc.node('a').x,w.doc.node('a').y
    drag((360,200),(420,260));assert w.doc.comment('g').w==460 and w.doc.comment('g').h==300
    assert (w.doc.node('a').x,w.doc.node('a').y)==original
    assert 'updates/s' not in w.metrics.text()
    # Empty-space rectangle selection and movement of the selected area.
    setup(Document(nodes=[copy.deepcopy(a),copy.deepcopy(b)]));w.doc.node('a').x=0;w.doc.node('a').y=0;w.doc.node('b').x=400;w.doc.node('b').y=0;w.rebuild()
    drag((-20,-20),(660,180));assert {i.key for i in w.scene.selectedItems()}=={'a','b'}
    drag((80,20),(120,60));assert w.doc.node('a').x==40 and w.doc.node('b').x==440
    # Free-end creation, extension and actual double-click property editing.
    w.start_wire(('a','q'));w.commit_wire(end=QPointF(340,100));free=w.doc.wires[-1];key=free.id
    click(340,100);assert w.pending_wire==key
    w.commit_wire(second=('b','d'));assert len(w.doc.wires)==1 and w.doc.wires[0].target==('b','d')
    def edit_current_dialog():
        dialog=app.activeModalWidget();assert isinstance(dialog,EditorDialog)
        dialog.fields['name'].setText('renamed_receiver');dialog.accept()
    QTimer.singleShot(0,edit_current_dialog)
    QTest.mouseDClick(w.view.viewport(),Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,w.view.mapFromScene(QPointF(520,60)))
    app.processEvents();assert w.doc.node('b').name=='renamed_receiver'
    # Property dialog validation and generated inline interface.
    d=EditorDialog(w,Node());assert 'w' not in d.fields and 'h' not in d.fields;d.fields['module'].setText('pipe');d.fields['name'].setText('u_pipe');d.boxes['inputs'].setPlainText('[ WIDTH - 1 : 0 ]data')
    d.boxes['outputs'].setPlainText('[WIDTH-1:0]result');d.boxes['params'].setPlainText('WIDTH = 8');d.boxes['transforms'].setPlainText('data = $');d.accept();assert d.value.inputs[0].width(d.value.params)==8
    n=Node(kind='inline',name='logic_block');d=InlineDialog(w,n);source='input logic [7:0] data;\noutput logic [7:0] result;\nassign result = data + 1;\n';d.text.setPlainText(source);d.accept();assert d.value.hdl_source==source and d.value.inputs[0].name=='data'
    d=CommentDialog(w,TextComment());d.text.setPlainText('Documentation');d.kind.setCurrentIndex(1);d.accept();assert d.value.kind=='group'
    # Minimum-sized dialogs center on the active view and keep buttons visible.
    w.resize(780,700);app.processEvents()
    for d in [DeclarationsDialog(w,''),EditorDialog(w,Node()),CommentDialog(w,TextComment()),InlineDialog(w,n)]:
        d.resize(d.minimumSize());d.show();app.processEvents()
        assert d.button_box.geometry().bottom()<=d.height()
        center=w.view.mapToGlobal(w.view.rect().center());screen=d.screen().availableGeometry()
        expected=max(screen.left(),min(center.x()-d.width()//2,screen.right()-d.width()))
        assert abs(d.pos().x()-expected)<8
        d.reject()
    # File operations: save / save-as, repeat silent export, raw inline recovery, PNG.
    topin=Node(id='i',kind='input',name='data',x=0,y=0,inputs=[],outputs=[Port('data','7:0')]);topin.normalize()
    topout=Node(id='o',kind='output',name='result',x=900,y=0,inputs=[Port('result','7:0')],outputs=[]);topout.normalize()
    inline=Node(id='logic',kind='inline',name='logic_block',x=400,y=0);update=None
    from inline_hdl import update_interface
    update_interface(inline,source)
    doc=Document(nodes=[topin,inline,topout],language='systemverilog');doc.connect(('i','data'),('logic','data'));doc.connect(('logic','result'),('o','result'));setup(doc)
    with tempfile.TemporaryDirectory() as tmp:
        tmp=Path(tmp);schematic=tmp/'schematic.vsch';other=tmp/'copy.vsch';hdl=tmp/'top_design.sv';png=tmp/'diagram.png'
        assert w.save(path=schematic);assert Document.load(schematic).serialize()==w.doc.serialize()
        assert w.save(True,path=other) and w.path==other
        assert w.export(path=hdl),errors;assert 'assign result = data + 1;' in hdl.read_text();assert 'module top_design' in hdl.read_text()
        assert w.export();assert Path(w.output_path.text()).resolve()==hdl.resolve()
        assert w.save();assert Path(Document.load(other).export_path).resolve()==hdl.resolve()
        assert source in other.read_text()
        state=w.doc.serialize();w.select('node','logic');width,height=w.render_png(png)
        image=QImage(str(png));assert not image.isNull() and image.width()==width and image.height()==height
        assert w.doc.serialize()==state and w.node_items['logic'].isSelected()
    for mode in ('Dots','Lines','Off'):w.grid_choice.setCurrentText(mode);app.processEvents();assert w.view.grid_mode==mode
    if len(sys.argv)>1:
        assert w.load(sys.argv[1]);w.fit();app.processEvents();w.view.viewport().repaint()
    assert not errors,errors
    print('Qt full editor: drawing/preview, branches, labels, resizing, replacement, error highlighting, groups, copy, undo, dialogs, save/export/PNG OK')
finally:
    QMessageBox.warning=old_warning;w.cancel_drawing();w.drag=None;w.saved=w.doc.serialize();w.close()
