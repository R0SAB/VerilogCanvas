import copy
import unittest
from model import Document,Node,Port,DesignError,COORD_LIMIT,resize_node
from hdl_import import modules_from_text

class NumericRangeTests(unittest.TestCase):
    def test_parameter_range_numeric_without_rewriting_source(self):
        p=Port('data','IN_MSB:0')
        self.assertEqual(p.dimensions_text({'IN_MSB':'15'}),('[15:0]',''))
        self.assertEqual(p.label(),'[IN_MSB:0]data')
        self.assertEqual(p.dimensions_text({'IN_MSB':'31'}),('[31:0]',''))

    def test_packed_unpacked_and_ascending(self):
        p=Port('data','0:W-1',packed_extra=['LANES-1:0'],unpacked=['0:DEPTH-1'])
        self.assertEqual(p.dimensions_text({'W':'8','LANES':'2','DEPTH':'4'}),('[0:7][1:0]','[0:3]'))

    def test_derived_parameter_and_clog2(self):
        p=Port('a','$clog2(DEPTH)-1:0')
        self.assertEqual(p.dimensions_text({'DEPTH':'BASE*2','BASE':'16'}),('[4:0]',''))
        self.assertEqual(Port('clk').dimensions_text({}),('',''))

    def test_import_keeps_symbolic_width_editable(self):
        n=modules_from_text('module m #(parameter IN_MSB=15)(input [IN_MSB:0] a); endmodule')[0].to_node()
        self.assertEqual(n.inputs[0].span,'IN_MSB:0')
        self.assertEqual(n.inputs[0].dimensions_text(n.params),('[15:0]',''))

class ExtendedCoordinatesTests(unittest.TestCase):
    def test_negative_nodes_wires_labels_roundtrip(self):
        n=Node(id='m',x=-2000000,y=-3000000);n.normalize()
        d=Document(nodes=[n]);w=d.connect(('m','y'),('m','a'),points=[[-1999680,-3000020]])
        d.label_wire(w.id,'feedback')
        restored=Document.deserialize(d.serialize())
        self.assertEqual(restored.serialize(),d.serialize())
        self.assertIn('.a(feedback)',restored.verilog())

    def test_free_ends_in_negative_quadrants(self):
        n=Node(id='m',x=-200,y=-200);d=Document(nodes=[n])
        w=d.connect(('m','a'),end=[-400,-140]);d.validate()
        self.assertEqual(w.end,[-400,-140])

    def test_resize_crosses_origin(self):
        n=Node(x=20,y=20,w=240,h=160)
        resize_node(n,(20,20,260,180),'nw',-220,-160)
        self.assertEqual((n.x,n.y,n.w,n.h),(-220,-160,480,340))
        Document(nodes=[n]).validate()

    def test_large_valid_and_invalid_coordinates(self):
        d=Document(nodes=[Node(x=-COORD_LIMIT,y=COORD_LIMIT)])
        d.validate();d.nodes[0].x=-COORD_LIMIT-20
        with self.assertRaises(DesignError): d.validate()

    def test_reposition_preserves_export(self):
        n=Node(id='m');d=Document(nodes=[n]);d.connect(('m','y'),('m','a'))
        code=d.verilog();n.x=-20_000_000;n.y=30_000_000
        self.assertEqual(code,d.verilog())

if __name__=='__main__': unittest.main()
