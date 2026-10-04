import copy
import unittest
from model import Document,Node,Port,route,junction_point,nearest_segment,GRID

class PortClearanceTests(unittest.TestCase):
    def circuit(self):
        a=Node(id='a',name='driver',x=0,y=0,inputs=[],outputs=[Port('q')])
        b=Node(id='b',name='sink',x=600,y=0,inputs=[Port('d')],outputs=[])
        doc=Document(nodes=[a,b]);w=doc.connect(('a','q'),('b','d'))
        return doc,w

    def assert_geometry(self,doc,w):
        points=route(doc,w)
        for a,b in zip(points,points[1:]):
            self.assertTrue(a[0]==b[0] or a[1]==b[1],points)
        for reverse,ep in ((False,w.source),(True,w.target)):
            if not ep:continue
            seq=list(reversed(points)) if reverse else points
            p=seq[0];q=next(q for q in seq[1:] if q!=p)
            direction=1 if doc.node(ep[0]).source(ep[1]) else -1
            self.assertEqual(p[1],q[1],points)
            self.assertGreaterEqual((q[0]-p[0])*direction,GRID,points)
        for a,b,c in zip(points,points[1:],points[2:]):
            if a[0]==b[0]==c[0] or a[1]==b[1]==c[1]:
                self.assertGreaterEqual((b[0]-a[0])*(c[0]-b[0])+(b[1]-a[1])*(c[1]-b[1]),0,points)

    def test_vertical_block_movement_leaves_outward_stub(self):
        for node in ('a','b'):
            for y in (-160,-20,20,160):
                doc,w=self.circuit();doc.node(node).y=y
                self.assert_geometry(doc,w)
                doc.freeze_wire(w);self.assert_geometry(doc,w)
                clone=Document.deserialize(doc.serialize());self.assertEqual(route(clone,clone.wire(w.id)),route(doc,w))

    def test_drag_direct_segment_leaves_two_stubs(self):
        for dy in (-80,80):
            doc,w=self.circuit();doc.move_segment(w,0,0,dy,copy.deepcopy(w.vertices))
            self.assert_geometry(doc,w);self.assertEqual(len(route(doc,w)),6)

    def test_only_selected_segment_junction_moves(self):
        doc,w=self.circuit();branches=[]
        for i,pos in enumerate((.25,.75)):
            n=Node(id=f'b{i}',name=f'sink{i}',x=800,y=200+i*200,inputs=[Port('d')],outputs=[]);doc.nodes.append(n)
            branches.append(doc.connect((n.id,'d'),join_wire=w.id,join_position=pos))
        old=[junction_point(doc,b) for b in branches];doc.freeze_wire(w)
        doc.move_segment(w,0,0,80,copy.deepcopy(w.vertices))
        self.assert_geometry(doc,w)
        for i,(b,p) in enumerate(zip(branches,old)):
            self.assertEqual(junction_point(doc,b),(p[0],p[1]+80) if i==0 else p);self.assert_geometry(doc,b)
        self.assertEqual(len(doc.nets()),1);doc.validate()

    def test_branch_at_port_keeps_fixed_junction(self):
        doc,w=self.circuit();n=Node(id='c',name='third',x=800,y=300,inputs=[Port('d')],outputs=[]);doc.nodes.append(n)
        branch=doc.connect(('c','d'),join_wire=w.id,join_position=0)
        key=branch.join_vertex;doc.freeze_wire(w);doc.move_segment(w,0,0,80,copy.deepcopy(w.vertices))
        self.assertEqual(branch.join_vertex,key)
        self.assertEqual(junction_point(doc,branch),(240,60))
        self.assert_geometry(doc,w);self.assert_geometry(doc,branch);doc.validate()

    def test_branch_drag_beyond_host_has_no_retraced_tail(self):
        for offset in (-200,-40,40,200):
            doc,w=self.circuit();n=Node(id='c',name='third',x=800,y=300,inputs=[Port('d')],outputs=[]);doc.nodes.append(n)
            branch=doc.connect(('c','d'),join_wire=w.id,join_position=.5)
            doc.freeze_wire(branch)
            doc.move_segment(branch,0,offset,0,copy.deepcopy(branch.vertices))
            for wire in doc.wires:self.assert_geometry(doc,wire)
            self.assertIn(junction_point(doc,branch),route(doc,w));doc.validate()

    def test_crossing_does_not_connect_unrelated_wire(self):
        doc,w=self.circuit();n=Node(id='c',name='other',x=800,y=300,inputs=[Port('d')],outputs=[]);doc.nodes.append(n)
        other=doc.connect(('c','d'),end=[400,60]);before=len(doc.nets())
        doc.node('a').y=80;route(doc,w);self.assertIsNone(other.join_wire);self.assertEqual(len(doc.nets()),before)
