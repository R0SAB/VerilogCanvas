"""Regression: dangling end -> plain corner -> one T junction."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPointF,Qt
from model import Document,Node,Port,project_to_path,route
from qt_editor import EditorWindow

app=QApplication([]);window=EditorWindow();window.show();app.processEvents()

def markers(point):
    dots=[i for i in window.wire_items.values() if i.draw_joint and tuple(i.joint)==point]
    ends=[(i,side) for i in window.wire_items.values() for side,p in i.loose if tuple(p)==point]
    return len(dots),len(ends)

try:
    for attach_to_branch in (False,True):
        a=Node(id='a',name='source_block',x=0,y=0,inputs=[],outputs=[Port('q')])
        b=Node(id='b',name='lower_sink',x=600,y=300,inputs=[Port('d')],outputs=[])
        c=Node(id='c',name='right_sink',x=600,y=0,inputs=[Port('d')],outputs=[])
        window.doc=Document(nodes=[a,b,c]);window.rebuild();window.history=[];window.future=[]
        joint=(360,60)
        window.start_wire(('b','d'));window.bends=[[360,360]];window.commit_wire(end=joint)
        host=window.doc.wires[0];assert markers(joint)==(0,1)
        window.start_wire(('a','q'));window.commit_wire(join_wire=host.id,join_position=project_to_path(route(window.doc,host),*joint)[0])
        branch=window.doc.wires[-1];assert markers(joint)==(0,0),markers(joint)
        target=branch if attach_to_branch else host
        window.start_wire(('c','d'));window.commit_wire(join_wire=target.id,join_position=project_to_path(route(window.doc,target),*joint)[0])
        third=window.doc.wires[-1];assert markers(joint)==(1,0),markers(joint)
        window.undo();assert markers(joint)==(0,0)
        window.undo();assert markers(joint)==(0,1)
        window.redo();window.redo();assert markers(joint)==(1,0)
        # Deleting the third branch restores a bend; deleting the second restores a free tip.
        window.select('wire',third.id);window.delete();assert markers(joint)==(0,0)
        window.select('wire',branch.id);window.delete();assert markers(joint)==(0,1)
        # Coincident but electrically separate loose ends must not be joined by the renderer.
        window.start_wire(('a','q'));window.commit_wire(end=joint)
        assert markers(joint)==(0,2),markers(joint)
    print('Qt junction markers: free tip, two-wire corner, unique three-wire dot, nested attachments, undo/redo/delete and unrelated crossing OK')
finally:
    window.drag=None;window.saved=window.doc.serialize();window.close()
