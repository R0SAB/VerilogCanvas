import unittest
from model import Document, Node, Port, TextComment, route
try:
    import pyslang
    from pyslang import ast, syntax
except ImportError:
    pyslang=None

def grouped_design():
    a=Node(id='a',module='source',name='u_a',x=200,y=200,inputs=[],outputs=[Port('y','7:0')])
    b=Node(id='b',module='sink',name='u_b',x=600,y=200,inputs=[Port('a','7:0')],outputs=[])
    outside=Node(id='outside',module='source',name='u_outside',x=1400,y=200,inputs=[],outputs=[Port('y','7:0')])
    group=TextComment(id='g',kind='group',text='PROCESSING',x=100,y=100,w=1000,h=500)
    d=Document(nodes=[a,outside,b],comments=[group,TextComment(text='Documentation only',x=20,y=800)])
    d.connect(('a','y'),('b','a'),points=[[480,260],[480,400],[560,400]])
    return d

class GroupTests(unittest.TestCase):
    def test_membership_and_overlap(self):
        d=grouped_design()
        self.assertEqual(d.module_groups(),{'a':'g','b':'g'})
        d.node('b').x=1000
        self.assertNotIn('b',d.module_groups()) # partial containment does not count
        d.comments.append(TextComment(id='small',kind='group',text='Inner',x=180,y=180,w=300,h=200))
        self.assertEqual(d.module_groups()['a'],'small')

    def test_move_internal_routes_and_fixed_membership(self):
        d=grouped_design();old=route(d,d.wires[0]);contents=d.group_contents('g')
        d.move_group('g',100,60,contents)
        self.assertEqual(route(d,d.wires[0]),[(x+100,y+60) for x,y in old])
        self.assertEqual((d.node('outside').x,d.node('outside').y),(1400,200))
        self.assertEqual((d.comment('g').x,d.comment('g').y),(200,160))
        self.assertEqual(Document.deserialize(d.serialize()).serialize(),d.serialize())

    def test_hdl_sections_and_contiguous_instances(self):
        d=grouped_design();code=d.verilog()
        header='// ############ PROCESSING #############'
        self.assertLess(code.index(header),code.index('wire [7:0] syn_net_0;'))
        self.assertLess(code.index('wire [7:0] syn_net_0;'),code.index('source\nu_a\n('))
        self.assertLess(code.index('sink\nu_b\n('),code.index('source\nu_outside\n('))
        self.assertEqual(code.count('wire [7:0] syn_net_0;'),1)
        self.assertNotIn('Documentation only',code)

    def test_shared_nets_are_global(self):
        d=grouped_design()
        d.node('outside').module='sink';d.node('outside').outputs=[];d.node('outside').inputs=[Port('a','7:0')]
        d.connect(('a','y'),('outside','a'))
        code=d.verilog()
        self.assertLess(code.index('wire [7:0] syn_net_0;'),code.index('// ############ PROCESSING'))
        self.assertEqual(code.count('wire [7:0] syn_net_0;'),1)

    def test_internal_branch_moves_with_group(self):
        d=grouped_design()
        c=Node(id='c',module='sink',name='u_c',x=600,y=400,inputs=[Port('a','7:0')],outputs=[])
        d.nodes.append(c)
        branch=d.connect(('c','a'),end=[480,300],join_wire=d.wires[0].id)
        old=route(d,branch);d.move_group('g',-200,-100)
        self.assertEqual(route(d,branch),[(x-200,y-100) for x,y in old])

    def test_transform_references_keep_nets_global(self):
        d=grouped_design();d.label_wire(d.wires[0].id,'payload')
        n=d.node('outside');n.module='sink';n.inputs=[Port('a','7:0')];n.outputs=[];n.transforms={'a':'$ ^ payload'}
        d.nodes.append(Node(id='src',module='source',name='u_src',x=1800,inputs=[],outputs=[Port('y','7:0')]))
        d.connect(('src','y'),('outside','a'))
        code=d.verilog()
        self.assertLess(code.index('wire [7:0] payload;'),code.index('// ############ PROCESSING'))

    def test_multiline_header_stays_commented(self):
        d=grouped_design();d.comment('g').text='Line one\nendmodule\nLine three'
        code=d.verilog()
        self.assertIn('// ############ endmodule #############',code)
        self.assertEqual(code.splitlines().count('endmodule'),1)

    @unittest.skipIf(pyslang is None,'Optional HDL compiler')
    def test_compile_both_languages(self):
        for language in ('verilog','systemverilog'):
            d=grouped_design();comp=ast.Compilation()
            comp.addSyntaxTree(syntax.SyntaxTree.fromText('module source(output [7:0] y); assign y=8\'h55; endmodule\nmodule sink(input [7:0] a); endmodule\n'+d.verilog(language)))
            comp.getRoot();diag=comp.getAllDiagnostics()
            self.assertFalse(any(x.isError() for x in diag),pyslang.DiagnosticEngine.reportAll(comp.sourceManager,diag))
