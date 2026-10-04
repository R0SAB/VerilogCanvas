import copy
import json
import tempfile
import unittest
from pathlib import Path
from model import *


def fixture():
    a=Node(id='in',kind='input',name='data_in',inputs=[],outputs=[Port('data_in','7:0')],x=40,y=100)
    m=Node(id='m',module='data_pipe',name='u_pipe',inputs=[Port('a','WIDTH-1:0')],outputs=[Port('y','WIDTH-1:0')],params={'WIDTH':'8'},x=400,y=100)
    b=Node(id='out',kind='output',name='data_out',inputs=[Port('data_out','7:0')],outputs=[],x=800,y=100)
    a.normalize();b.normalize()
    d=Document('example_top',[a,m,b]); d.connect(('in','data_in'),('m','a')); d.connect(('m','y'),('out','data_out'))
    return d

class ModelTests(unittest.TestCase):
    def test_port_parser(self):
        self.assertEqual(Port.parse(' [7:0] data ').width({}),8)
        self.assertEqual(Port.parse('flag').width({}),1)
        self.assertEqual(Port.parse('[0:7]data').declaration({}),'[0:7] ')
        self.assertEqual(Port.parse('[3:3]data').width({}),1)
        for name in ['wire','a b','3port','[7]foo','[7:0]']:
            with self.assertRaises(DesignError): Port.parse(name)

    def test_integer_expr(self):
        for expr,expected in [('WIDTH-1',7),('$clog2(17)',5),("8'hFF",255),("4'h1f",15),("8'shff",-1),('1 << 3',8),('-7 / 3',-2),('-7 % 3',-1)]:
            self.assertEqual(integer_expr(expr,{'WIDTH':'8'}),expected)
        for expr in ['__import__("os")','x','1/0','1<<999','2**999','1.5','a.b']:
            with self.assertRaises(DesignError): integer_expr(expr,{})
        with self.assertRaises(DesignError): integer_expr('A',{'A':'B','B':'A'})

    def test_export(self):
        code=fixture().verilog()
        for text in ['module example_top (','input wire [7:0] data_in','output wire [7:0] data_out','.WIDTH(8)','data_pipe\n#(\n    .WIDTH(8)\n)\nu_pipe\n(','.a(data_in)','.y(data_out)']:
            self.assertIn(text,code)
        self.assertEqual(code,fixture().verilog())

    def test_fanout(self):
        d=fixture(); d.nodes.append(Node(id='m2',module='data_pipe',name='u_pipe2',inputs=[Port('a','7:0')],outputs=[]))
        d.connect(('m2','a'),('m','y'))
        code=d.verilog(); self.assertEqual(code.count('output wire [7:0] data_out'),1); self.assertIn('.a(data_out)',code)

    def test_width_mismatch_atomic(self):
        d=fixture(); d.wires=[]; d.nodes[1].inputs=[Port('a')]
        with self.assertRaises(DesignError): d.connect(('in','data_in'),('m','a'))
        self.assertEqual(d.wires,[])

    def test_multiple_drivers(self):
        d=fixture()
        with self.assertRaises(DesignError): d.connect(('in','data_in'),('out','data_out'))
        self.assertEqual(len(d.wires),2)

    def test_invalid_direction(self):
        d=fixture()
        with self.assertRaises(DesignError): d.connect(('in','data_in'),('m','y'))

    def test_unconnected(self):
        d=fixture(); d.wires.pop()
        with self.assertRaises(DesignError): d.verilog()
        d.nodes.pop(); self.assertIn('.y()',d.verilog())

    def test_roundtrip(self):
        d=fixture(); d.wires[0].points=[[300,300],[360,300]]
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'roundtrip.vsch'; d.save(p); other=Document.load(p)
            self.assertEqual(other.serialize(),d.serialize()); self.assertEqual(other.verilog(),d.verilog())

    def test_collision(self):
        d=fixture(); d.nodes[1].name='syn_net_0';d.remove_node('out')
        d.nodes.append(Node(id='sink',name='u_sink',inputs=[Port('a','7:0')],outputs=[]))
        d.connect(('m','y'),('sink','a'))
        code=d.verilog(); self.assertNotIn('wire [7:0] syn_net_0;',code); self.assertIn('wire [7:0] syn_net_1;',code)

    def test_duplicate_name(self):
        d=fixture(); d.nodes[1].name='data_in'
        with self.assertRaises(DesignError): d.validate()

    def test_bad_file(self):
        d=fixture().serialize(); d['version']=999
        with self.assertRaises(DesignError): Document.deserialize(d)
        d=fixture().serialize(); d['wires'][0]['source']=['unknown','x']
        with self.assertRaises(DesignError): Document.deserialize(d)

    def test_route_orthogonal_grid(self):
        d=fixture()
        for custom in [[],[[300,400],[700,200]]]:
            d.wires[0].points=custom
            for x in [40,1000]:
                d.nodes[0].x=x
                pts=route(d,d.wires[0]); self.assertEqual(pts[0],d.nodes[0].endpoint('data_in')); self.assertEqual(pts[-1],d.nodes[1].endpoint('a'))
                for a,b in zip(pts,pts[1:]):
                    self.assertTrue(a[0]==b[0] or a[1]==b[1]); self.assertTrue(all(v%20==0 for v in (*a,*b)))

    def test_parameter_reference_expansion(self):
        d=fixture(); d.nodes[1].params={'WIDTH':'8','DEPTH':'WIDTH * 2','MODE':'"WIDTH"'}
        code=d.verilog()
        self.assertIn('.DEPTH((8) * 2)',code)
        self.assertIn('.MODE("WIDTH")',code)
        with self.assertRaises(DesignError): parameter_value('A',{'A':'B','B':'A'})

    def test_empty_and_scalar(self):
        self.assertIn('module top (\n);',Document().verilog())
        a=Node(id='a',kind='input',name='clk',inputs=[],outputs=[Port('clk')]); b=Node(id='b',kind='output',name='clk_out',inputs=[Port('clk_out')],outputs=[])
        d=Document(nodes=[a,b]); d.connect(('a','clk'),('b','clk_out'))
        self.assertIn('assign clk_out = clk;',d.verilog()); self.assertNotIn('[0:0]',d.verilog())

    def test_parameter_expressions(self):
        for value in ['8',"8'hff",'"FAST"','{4{2\'b10}}','(4 + 4)']:
            self.assertEqual(expression(value),value)
        for value in ['1; wire attack','(1+2','1 // comment','"unterminated']:
            with self.assertRaises(DesignError): expression(value)

if __name__=='__main__': unittest.main()
