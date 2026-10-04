import unittest
from model import Document,Node,Port,TextComment,DesignError
try:
    import pyslang
    from pyslang import ast,syntax
except ImportError:
    pyslang=None

def design():
    a=Node(id='in',kind='input',name='data_in',inputs=[],outputs=[Port('data_in','7:0')],x=100,y=100)
    b=Node(id='m',module='pass_through',name='u_pass',inputs=[Port('a','7:0')],outputs=[Port('q','7:0')],x=500,y=100)
    c=Node(id='out',kind='output',name='data_out',inputs=[Port('data_out','7:0')],outputs=[],x=900,y=100)
    a.normalize();c.normalize()
    d=Document(nodes=[a,b,c])
    wi=d.connect(('in','data_in'),('m','a'));wo=d.connect(('m','q'),('out','data_out'))
    return d,wi,wo

class PortNetTests(unittest.TestCase):
    def test_same_port_names_no_duplicate_net_or_assign(self):
        d,wi,wo=design();d.label_wire(wi.id,'data_in');d.label_wire(wo.id,'data_out')
        for dx in range(-100,101,20):
            d.node('m').x=500+dx;d.validate();code=d.verilog()
            self.assertNotIn('syn_net_',code)
            self.assertNotIn('assign ',code)
            self.assertIn('.a(data_in)',code);self.assertIn('.q(data_out)',code)
            self.assertEqual(code.count('wire [7:0] data_in'),1)
            self.assertEqual(code.count('wire [7:0] data_out'),1)

    def test_remote_label_is_top_port_net(self):
        d,wi,wo=design();d.remove_wire(wi.id)
        remote=d.connect(('m','a'),end=[400,160]);d.label_wire(remote.id,'data_in')
        self.assertIn(('in','data_in'),next(n for n in d.nets() if n.name=='data_in').ports)
        self.assertIn('.a(data_in)',d.verilog())
        # The alias also joins an existing unlabelled wire of the port.
        extra=d.connect(('in','data_in'),end=[380,160]);d.validate()
        net=next(n for n in d.nets() if n.name=='data_in')
        self.assertIn(extra.id,net.wires)

    def test_alias_cannot_create_multiple_drivers(self):
        d,wi,wo=design()
        with self.assertRaises(DesignError):d.label_wire(wo.id,'data_in')
        self.assertEqual(d.labels,[])

    def test_ports_in_group_and_global_declarations(self):
        d,wi,wo=design();d.comments=[TextComment(id='g',text='All ports',kind='group',x=80,y=80,w=1200,h=400)]
        self.assertEqual(set(d.module_groups()),{'in','m','out'})
        d.move_group('g',60,40)
        self.assertEqual((d.node('in').x,d.node('out').x),(160,960))
        code=d.verilog()
        self.assertNotIn('syn_net_',code);self.assertNotIn('assign ',code)
        self.assertLess(code.index('input wire [7:0] data_in'),code.index('// ############ All ports'))

    @unittest.skipIf(pyslang is None,'Optional HDL compiler')
    def test_compile_port_aliases_in_groups(self):
        for language in ('verilog','systemverilog'):
            d,wi,wo=design();d.label_wire(wi.id,'data_in');d.label_wire(wo.id,'data_out')
            d.comments=[TextComment(id='g',text='PORTS',kind='group',x=80,y=80,w=1200,h=400)]
            comp=ast.Compilation();comp.addSyntaxTree(syntax.SyntaxTree.fromText('module pass_through(input [7:0] a, output [7:0] q);assign q=a;endmodule\n'+d.verilog(language)))
            comp.getRoot();diag=comp.getAllDiagnostics()
            self.assertFalse(any(x.isError() for x in diag),pyslang.DiagnosticEngine.reportAll(comp.sourceManager,diag))
