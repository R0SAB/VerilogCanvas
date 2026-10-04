import copy
import unittest
from model import Document,Node,Port,route,project_to_path,junction_point,nearest_segment

class ConsumedTipTests(unittest.TestCase):
    def design(self,nested=True):
        nodes=[Node(id='left',name='driver',x=0,y=0,inputs=[],outputs=[Port('q')]),
               Node(id='lower',name='lower_sink',x=800,y=400,inputs=[Port('d')],outputs=[]),
               Node(id='right',name='right_sink',x=800,y=0,inputs=[Port('d')],outputs=[])]
        d=Document(nodes=nodes)
        host=d.connect(('lower','d'),end=[400,60],drawn_path=[(800,460),(400,460),(400,60)])
        left=d.connect(('left','q'),join_wire=host.id,join_position=0,drawn_path=[(240,60),(400,60)])
        target=left if nested else host
        right=d.connect(('right','d'),join_wire=target.id,join_position=project_to_path(route(d,target),400,60)[0],drawn_path=[(800,60),(400,60)])
        return d,host,left,right

    def move(self,d,w,x,y,dy):
        d.freeze_wire(w);i=nearest_segment(route(d,w),x,y);d.move_segment(w,i,0,dy,copy.deepcopy(w.vertices));d.validate()

    def test_nested_arms_move_independently_past_old_tip(self):
        for nested in (True,False):
            d,host,left,right=self.design(nested);right_before=route(d,right)
            self.move(d,left,320,60,80)
            self.assertEqual(route(d,right),right_before)
            self.assertEqual(junction_point(d,left),(400,140))
            self.move(d,right,600,60,-80)
            self.assertEqual(junction_point(d,right),(400,-20))
            self.assertEqual(junction_point(d,left),(400,140))
            self.assertEqual(route(d,host)[0],(400,-20))
            self.assertEqual(len(d.nets()),1)

    def test_no_ghost_tip_when_both_arms_move_down(self):
        d,host,left,right=self.design()
        self.move(d,left,320,60,80);self.move(d,right,600,60,120)
        self.assertEqual(route(d,host)[0],(400,140))
        self.assertNotIn((400,60),route(d,host))
        self.assertEqual(junction_point(d,right),(400,180))
        clone=Document.deserialize(d.serialize());self.assertEqual(clone.verilog(),d.verilog())

    def test_delete_only_free_terminal_edge(self):
        d,host,left,right=self.design();d.remove_wire(left.id);d.remove_wire(right.id)
        label=d.label_wire(host.id,'data_net');d.freeze_wire(host)
        self.assertTrue(d.remove_free_segment(host.id,0))
        self.assertEqual(route(d,host),[(400,460),(800,460)])
        self.assertEqual(host.target,('lower','d'));self.assertIn(label,d.labels);d.validate()
        self.assertTrue(d.remove_free_segment(host.id,0));self.assertFalse(d.wires)

    def test_delete_tip_stops_at_existing_junction(self):
        d,host,left,right=self.design(False)
        # Add a genuinely free tail above the physical node.
        d.freeze_wire(host);host.vertices.insert(0,['tip',400,0]);host.set_loose('start',[400,0])
        self.assertTrue(d.remove_free_segment(host.id,0))
        self.assertEqual(junction_point(d,left),(400,60));self.assertEqual(junction_point(d,right),(400,60))
        self.assertEqual(route(d,host)[0],(400,60));d.validate()
