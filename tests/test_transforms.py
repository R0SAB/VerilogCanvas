import copy
import unittest
from model import Document, Node, Port, DesignError, transform_expression
try:
    import pyslang
    from pyslang import ast, syntax
except ImportError:
    pyslang = None

def example():
    source = Node(id='source', kind='input', name='modulation', inputs=[], outputs=[Port('modulation','2:0')])
    sink = Node(id='sink', module='agc', name='inst_agc', inputs=[Port('mode')], outputs=[],
                transforms={'mode': "($ == MOD_AM) ? 1'b1 : 1'b0"}, x=700)
    doc = Document(nodes=[source,sink], language='systemverilog',
                   declarations="typedef enum logic [2:0] {MOD_AM = 3'd0, MOD_FM = 3'd1} modulation_t;")
    doc.connect(('source','modulation'),('sink','mode'))
    return doc

class TransformTests(unittest.TestCase):
    def test_export_and_roundtrip(self):
        doc=example()
        text=doc.verilog()
        self.assertIn(".mode((modulation == MOD_AM) ? 1'b1 : 1'b0)",text)
        self.assertIn('input logic [2:0] modulation',text);self.assertNotIn('syn_net_',text)
        self.assertLess(text.index('typedef enum'),text.index('agc\ninst_agc\n('))
        self.assertEqual(Document.deserialize(doc.serialize()).verilog(),text)

    def test_token_replacement(self):
        self.assertEqual(transform_expression('$signed($) + $ + foo$bar + "$"','bus'), '$signed(bus) + bus + foo$bar + "$"')
        for value in ('MOD_AM ? 1 : 0', '$; bad', '($', '"$"', '$clog2(8)'):
            with self.subTest(value=value), self.assertRaises(DesignError): transform_expression(value)

    def test_direct_fanout_still_validated(self):
        doc=example(); other=Node(id='other',name='u_other',inputs=[Port('a')],outputs=[])
        doc.nodes.append(other)
        with self.assertRaises(DesignError): doc.connect(('source','modulation'),('other','a'))
        other.inputs[0].span='2:0'
        doc.connect(('source','modulation'),('other','a'))
        self.assertIn('.a(modulation)',doc.verilog())
        doc.node('sink').transforms={}
        with self.assertRaises(DesignError): doc.validate()

    def test_missing_source_and_wrong_port(self):
        doc=example();doc.wires=[]
        with self.assertRaises(DesignError):doc.verilog()
        doc.node('sink').transforms={'bad':'$'}
        with self.assertRaises(DesignError):doc.validate()

    def test_remote_labels_and_generated_name(self):
        doc=example();doc.wires=[]
        a=doc.connect(('source','modulation'),end=[500,220])
        b=doc.connect(('sink','mode'),end=[600,220])
        doc.label_wire(a.id,'selected_mode');doc.label_wire(b.id,'selected_mode')
        self.assertIn('(selected_mode == MOD_AM)',doc.verilog())
        doc.labels=[];doc.wires=[]
        doc.connect(('source','modulation'),('sink','mode'))
        doc.declarations+='\nlogic syn_net_0;'
        self.assertIn('(modulation == MOD_AM)',doc.verilog())

    @unittest.skipIf(pyslang is None,'Optional HDL compiler')
    def test_compile_enum_and_slice(self):
        for expr in ("($ == MOD_AM) ? 1'b1 : 1'b0", '$[0]', '|$'):
            doc=example();doc.node('sink').transforms['mode']=expr
            compilation=ast.Compilation()
            compilation.addSyntaxTree(syntax.SyntaxTree.fromText('module agc(input logic mode); endmodule\n'+doc.verilog()))
            compilation.getRoot();diag=compilation.getAllDiagnostics()
            self.assertFalse(any(d.isError() for d in diag),pyslang.DiagnosticEngine.reportAll(compilation.sourceManager,diag))
