import copy
import unittest
from model import Document,Node,Port,NetLabel,DesignError,route,resize_node,path_position,project_to_path
from hdl_import import modules_from_text


def circuit():
    source=Node(id='src',kind='input',name='data_in',inputs=[],outputs=[Port('data_in','7:0')],x=40,y=80)
    sink=Node(id='dst',module='data_pipe',name='u_pipe',inputs=[Port('a','7:0')],outputs=[Port('y','7:0')],x=600,y=100)
    source.normalize()
    return Document('test_top',[source,sink])


def labelled_circuit():
    d=circuit()
    a=d.connect(('src','data_in'),end=[400,140])
    b=d.connect(('dst','a'),end=[500,160])
    d.label_wire(a.id,'payload');d.label_wire(b.id,'payload')
    return d,a,b

class LabelTests(unittest.TestCase):
    def test_disconnected_stubs_join(self):
        d,a,b=labelled_circuit(); code=d.verilog()
        self.assertEqual(len(d.nets()),1)
        self.assertIn('wire [7:0] payload;',code)
        self.assertIn('assign payload = data_in;',code)
        self.assertIn('.a(payload)',code)
        self.assertNotIn('syn_net_',code)

    def test_undriven_stub_saved_but_not_exported(self):
        d=circuit();d.connect(('dst','a'),end=[500,160]);d.validate()
        Document.deserialize(d.serialize())
        with self.assertRaisesRegex(DesignError,'no driver'): d.verilog()

    def test_different_names_do_not_connect(self):
        d,a,b=labelled_circuit();d.label_wire(b.id,'different')
        self.assertEqual(len(d.nets()),2)
        with self.assertRaises(DesignError): d.verilog()

    def test_multiple_sources_rejected_atomically(self):
        d,a,b=labelled_circuit()
        extra=Node(id='src2',kind='input',name='other_input',inputs=[],outputs=[Port('other_input','7:0')]);d.nodes.append(extra)
        c=d.connect(('src2','other_input'),end=[500,400]);before=d.serialize()
        with self.assertRaisesRegex(DesignError,'Multiple drivers'): d.label_wire(c.id,'payload')
        self.assertEqual(d.serialize(),before)

    def test_width_mismatch_rejected_atomically(self):
        d,a,b=labelled_circuit();extra=Node(id='dst2',name='u_second',inputs=[Port('flag')],outputs=[]);d.nodes.append(extra)
        c=d.connect(('dst2','flag'),end=[400,400]);before=d.serialize()
        with self.assertRaisesRegex(DesignError,'Width mismatch'): d.label_wire(c.id,'payload')
        self.assertEqual(d.serialize(),before)

    def test_conflicting_names_on_physical_net(self):
        d=circuit();a=d.connect(('src','data_in'),('dst','a'));b=d.connect(('src','data_in'),end=[400,140]);d.label_wire(a.id,'bus_a')
        with self.assertRaisesRegex(DesignError,'Conflicting label names'): d.label_wire(b.id,'bus_b')

    def test_fanout_remote_sink(self):
        d,a,b=labelled_circuit();extra=Node(id='dst2',name='u_second',inputs=[Port('a','7:0')],outputs=[]);d.nodes.append(extra)
        c=d.connect(('dst2','a'),end=[400,400]);d.label_wire(c.id,'payload')
        code=d.verilog();self.assertEqual(code.count('.a(payload)'),2);self.assertEqual(code.count('wire [7:0] payload;'),1)

    def test_label_same_as_connected_top_input(self):
        d,a,b=labelled_circuit();d.labels=[];d.label_wire(a.id,'data_in');d.label_wire(b.id,'data_in')
        code=d.verilog();self.assertNotIn('wire [7:0] data_in;',code);self.assertNotIn('assign data_in = data_in;',code)
        self.assertIn('.a(data_in)',code)

    def test_label_same_as_connected_top_output(self):
        d,a,b=labelled_circuit()
        out=Node(id='out',kind='output',name='result',inputs=[Port('result','7:0')],outputs=[]);d.nodes.append(out)
        w=d.connect(('dst','y'),('out','result'));d.label_wire(w.id,'result')
        code=d.verilog();self.assertIn('.y(result)',code);self.assertNotIn('assign result = result;',code)
        self.assertNotIn('wire [7:0] result;',code)

    def test_name_collision_with_unrelated_top_or_instance(self):
        d,a,b=labelled_circuit()
        for name in ['u_pipe','test_top','module','bad name']:
            with self.subTest(name=name),self.assertRaises(DesignError): d.label_wire(a.id,name)
        other=Node(id='unrelated',kind='input',name='spare',inputs=[],outputs=[Port('spare')]);d.nodes.append(other)
        with self.assertRaises(DesignError): d.label_wire(a.id,'spare')

    def test_synthetic_names_skip_user_labels(self):
        d,a,b=labelled_circuit();d.labels=[];d.label_wire(a.id,'syn_net_0');d.label_wire(b.id,'syn_net_0')
        d.connect(('dst','y'),end=[940,160])
        self.assertIn('wire [7:0] syn_net_1;',d.verilog())

    def test_delete_wire_removes_labels(self):
        d,a,b=labelled_circuit();d.remove_wire(a.id)
        self.assertEqual(len(d.labels),1);self.assertEqual(d.labels[0].wire_id,b.id);d.validate()
        with self.assertRaises(DesignError): d.verilog()

    def test_delete_node_preserves_stubs_and_labels(self):
        d,a,b=labelled_circuit();d.remove_node('dst');d.validate()
        self.assertEqual(len(d.wires),2);self.assertEqual(len(d.labels),2)
        self.assertFalse(d.wire(b.id).endpoints())

    def test_roundtrip_v3(self):
        d,a,b=labelled_circuit();copydoc=Document.deserialize(d.serialize())
        self.assertEqual(copydoc.serialize(),d.serialize());self.assertEqual(copydoc.verilog(),d.verilog())

    def test_extend_stub_keeps_label_and_id(self):
        d=circuit();a=d.connect(('src','data_in'),end=[400,140]);label=d.label_wire(a.id,'payload')
        d.connect(('src','data_in'),('dst','a'),replace_id=a.id)
        self.assertEqual(d.labels[0].id,label.id);self.assertIsNone(d.wires[0].end);self.assertIn('.a(payload)',d.verilog())

    def test_input_first_stub_and_route(self):
        d=circuit();w=d.connect(('dst','a'),points=[[400,200]],end=[380,200])
        self.assertIsNone(w.source);self.assertEqual(w.target,('dst','a'))
        pts=route(d,w);self.assertEqual(pts[0],(380,200));self.assertEqual(pts[-1],d.node('dst').endpoint('a'))
        for a,b in zip(pts,pts[1:]): self.assertTrue(a[0]==b[0] or a[1]==b[1])

    def test_open_end_overlap_not_electrical(self):
        d=circuit();d.connect(('src','data_in'),end=[400,140]);d.connect(('dst','a'),end=[400,140])
        self.assertEqual(len(d.nets()),2)
        with self.assertRaises(DesignError): d.verilog()

    def test_malformed_labels_and_wire(self):
        d,a,b=labelled_circuit();data=d.serialize();data['labels'][0]['wire_id']='missing'
        with self.assertRaises(DesignError): Document.deserialize(data)
        data=d.serialize();data['wires'][0]['end']=[3,5]
        with self.assertRaises(DesignError): Document.deserialize(data)
        data=d.serialize();data['labels'][0]['position']=float('nan')
        with self.assertRaises(DesignError): Document.deserialize(data)

class LayoutTests(unittest.TestCase):
    def test_compact_imported_ranges(self):
        n=modules_from_text('module pipe #(parameter WIDTH=8)(input logic [ WIDTH - 1 : 0 ] a [ 0 : 1 ], output logic [1:0][ WIDTH - 1 : 0 ] q); endmodule')[0].to_node()
        self.assertEqual(n.inputs[0].span,'WIDTH-1:0');self.assertEqual(n.inputs[0].unpacked,['0:1'])
        self.assertEqual(n.outputs[0].packed_extra,['WIDTH-1:0'])
        self.assertEqual(n.inputs[0].label(),'[WIDTH-1:0]a[0:1]')

    def test_old_spaced_ranges_display_compact(self):
        p=Port('a',' WIDTH - 1 : 0 ',packed_extra=[' 3 : 0 ']);self.assertEqual(p.label(),'[WIDTH-1:0][3:0]a')

    def test_resize_all_corners_grid_fixed_opposite(self):
        for corner in ['se','sw','ne','nw']:
            n=Node(x=100,y=100,w=300,h=240,params={'W':'8'});n.normalize();original=(n.x,n.y,n.x+n.w,n.y+n.h)
            resize_node(n,original,corner,51 if 'w' in corner else 517,41 if 'n' in corner else 479)
            self.assertTrue(all(v%20==0 for v in (n.x,n.y,n.w,n.h)))
            self.assertGreaterEqual(n.w,n.minimum_size()[0]);self.assertGreaterEqual(n.h,n.minimum_size()[1])
            self.assertEqual(n.x+n.w,original[2]) if 'w' in corner else self.assertEqual(n.x,original[0])
            self.assertEqual(n.y+n.h,original[3]) if 'n' in corner else self.assertEqual(n.y,original[1])

    def test_resize_minimum_parameters_space(self):
        n=Node(x=100,y=100,params={'W':'8','D':'4','MODE':'"FAST"'});n.normalize()
        resize_node(n,(n.x,n.y,n.x+n.w,n.y+n.h),'se',110,110)
        self.assertEqual((n.w,n.h),n.minimum_size())
        self.assertLess(n.parameters_y()+len(n.params)*20,n.y+n.h-16)

    def test_label_projection_follows_wire(self):
        points=[(0,0),(100,0),(100,100)]
        pos,dist=project_to_path(points,110,50);self.assertAlmostEqual(pos,.75);self.assertEqual(dist,100)
        self.assertEqual(path_position(points,pos),(100,50))

    def test_old_schema_expands_parameters_without_moving_ports(self):
        d=circuit();d.nodes[1].params={'W':'8'};old=d.serialize();old['version']=2
        ep=d.nodes[1].endpoint('a');restored=Document.deserialize(old)
        self.assertEqual(restored.nodes[1].endpoint('a'),ep)
        self.assertGreaterEqual(restored.nodes[1].h,restored.nodes[1].minimum_size()[1])

if __name__=='__main__': unittest.main()
