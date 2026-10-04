import copy
import unittest
from model import Document,Node,Port,route,junction_point,project_to_path,nearest_segment
from test_port_nets import design

class SegmentTests(unittest.TestCase):
    def test_export_unnamed_and_named_port_nets(self):
        d,wi,wo=design();code=d.verilog()
        self.assertIn('.a(data_in)',code);self.assertIn('.q(data_out)',code)
        self.assertNotIn('syn_net_',code);self.assertNotIn('assign ',code)
        d.label_wire(wi.id,'input_bus');d.label_wire(wo.id,'output_bus');code=d.verilog()
        self.assertIn('wire [7:0] input_bus;',code);self.assertIn('assign input_bus = data_in;',code)
        self.assertIn('wire [7:0] output_bus;',code);self.assertIn('assign data_out = output_bus;',code)
        self.assertIn('.a(input_bus)',code);self.assertIn('.q(output_bus)',code)

    def test_segment_constraints_and_endpoint_anchors(self):
        d,wi,wo=design();original=copy.deepcopy(wi.vertices)
        start,end=route(d,wi)[0],route(d,wi)[-1]
        d.move_segment(wi,0,80,60,original)
        points=route(d,wi)
        self.assertEqual(points[0],start);self.assertEqual(points[-1],end)
        self.assertTrue(any(a[1]==b[1]==220 for a,b in zip(points,points[1:])))
        d.freeze_wire(wi)
        index=next(i for i,(a,b) in enumerate(zip(route(d,wi),route(d,wi)[1:])) if a[0]==b[0] and a!=b)
        original=copy.deepcopy(wi.vertices);d.move_segment(wi,index,40,80,original)
        self.assertEqual(route(d,wi)[0],start);self.assertEqual(route(d,wi)[-1],end)
        self.assertTrue(all(a[0]==b[0] or a[1]==b[1] for a,b in zip(route(d,wi),route(d,wi)[1:])))
        d.validate();self.assertEqual(Document.deserialize(d.serialize()).serialize(),d.serialize())

    def test_junction_is_shared_vertex_and_branch_is_perpendicular(self):
        d,host,wo=design();n=Node(id='b',name='u_b',x=500,y=400,inputs=[Port('a','7:0')],outputs=[]);d.nodes.append(n)
        position=project_to_path(route(d,host),420,160)[0]
        branch=d.connect(('b','a'),end=[420,160],join_wire=host.id,join_position=position)
        self.assertIn(branch.join_vertex,[v[0] for v in host.vertices])
        self.assertIn((420,160),route(d,host))
        bp=route(d,branch);self.assertEqual(bp[0],(420,160));self.assertEqual(bp[1][0],420)
        self.assertNotEqual(bp[1][1],160)
        # Moving one parent segment moves its junction node and the attached branch.
        d.freeze_wire(host);i=nearest_segment(route(d,host),380,160)
        d.move_segment(host,i,0,40,copy.deepcopy(host.vertices))
        self.assertEqual(junction_point(d,branch),(420,200))
        self.assertIn((420,160),route(d,host))  # Unselected continuation stays at its original height.
        self.assertEqual(route(d,branch)[0],(420,200));d.validate()
        # Resetting the route must keep the electrical and geometric attachment.
        d.reset_wire_route(host);d.validate()
        self.assertIn(branch.join_vertex,[v[0] for v in host.vertices])
        self.assertEqual(len(d.nets()),2)

    def test_multiple_branches_share_one_vertex(self):
        d,host,wo=design()
        for index in range(2):
            n=Node(id=f'b{index}',name=f'u_b{index}',x=500,y=400+index*200,inputs=[Port('a','7:0')],outputs=[]);d.nodes.append(n)
            d.connect((n.id,'a'),end=[420,160],join_wire=host.id,join_position=project_to_path(route(d,host),420,160)[0])
        self.assertEqual(d.wires[-1].join_vertex,d.wires[-2].join_vertex)
        self.assertEqual(sum((v[1],v[2])==(420,160) for v in host.vertices),1)
