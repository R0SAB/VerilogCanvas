import unittest
from model import Document,Node,Port,DesignError,route,junction_point

def design():
    a=Node(id='a',kind='input',name='data',inputs=[],outputs=[Port('data','7:0')],x=80,y=100)
    a.normalize()
    b=Node(id='b',name='u_b',inputs=[Port('a','7:0')],outputs=[],x=800,y=100)
    c=Node(id='c',name='u_c',inputs=[Port('a','7:0')],outputs=[],x=800,y=400)
    d=Document(nodes=[a,b,c]);w=d.connect(('a','data'),('b','a'))
    return d,w

class JunctionTests(unittest.TestCase):
    def test_branch_export_roundtrip_and_move(self):
        d,w=design();b=d.connect(('c','a'),end=[560,160],join_wire=w.id)
        self.assertEqual(len(d.nets()),1)
        self.assertEqual(d.verilog().count('.a(data)'),2)
        self.assertEqual(Document.deserialize(d.serialize()).verilog(),d.verilog())
        p=junction_point(d,b);d.node('b').x+=200
        self.assertEqual(p,junction_point(d,b))
        self.assertEqual(route(d,b)[0],junction_point(d,b))

    def test_delete_host_detaches(self):
        d,w=design();b=d.connect(('c','a'),end=[560,160],join_wire=w.id)
        p=junction_point(d,b);d.remove_wire(w.id)
        self.assertIsNone(b.join_wire);self.assertEqual(b.end,list(p));d.validate()
        with self.assertRaises(DesignError):d.verilog()

    def test_conflicting_driver_width_and_cycle(self):
        d,w=design();d.node('c').inputs[0].span='3:0'
        with self.assertRaises(DesignError):d.connect(('c','a'),end=[560,160],join_wire=w.id)
        d.node('c').transforms={'a':'$[3:0]'}
        b=d.connect(('c','a'),end=[560,160],join_wire=w.id)
        other=Node(id='o',kind='input',name='other',inputs=[],outputs=[Port('other','7:0')]);other.normalize();d.nodes.append(other)
        with self.assertRaises(DesignError):d.connect(('o','other'),end=[560,160],join_wire=w.id)
        b.join_wire=b.id
        with self.assertRaises(DesignError):d.validate()

    def test_nested_labels_and_crossing(self):
        d,w=design();b=d.connect(('c','a'),end=[560,160])
        self.assertEqual(len(d.nets()),2) # coincident geometry is not connectivity
        b.join_wire=w.id;d.label_wire(b.id,'bus_data')
        n=Node(id='e',name='u_e',inputs=[Port('a','7:0')],outputs=[]);d.nodes.append(n)
        d.connect(('e','a'),end=[560,300],join_wire=b.id)
        self.assertEqual(len(d.nets()),1)
        self.assertEqual(d.verilog().count('.a(bus_data)'),3)
