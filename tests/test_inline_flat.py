import unittest
from model import Document,Node,Port,DesignError
from inline_hdl import update_interface,parse_inline
from test_inline_hdl import inline_design,ast,syntax

class FlatInlineTests(unittest.TestCase):
    def test_conflict_message_identifies_sources_and_differences(self):
        from inline_hdl import declaration_conflict
        old=Port('data','WIDTH-1:0',signed=True,unpacked=['0:3'])
        new=Port('data','7:0',two_state=True)
        message=str(declaration_conflict('data',old,{'WIDTH':'16'},'driver u_source.data',
                                         new,{},'Inline HDL block processing, port data'))
        for detail in ('u_source.data','processing','port data',
                       'packed dimensions: [15:0] -> [7:0]',
                       'array dimensions: [0:3] -> none',
                       'signedness: signed -> unsigned','state type: 4-state -> 2-state'):
            self.assertIn(detail,message)

    def compile(self,code):
        if ast:
            comp=ast.Compilation();comp.addSyntaxTree(syntax.SyntaxTree.fromText(code))
            self.assertFalse([str(d.code) for d in comp.getAllDiagnostics() if d.isError()],code)

    def test_body_unchanged_no_scope_no_prefix_no_self_assignment(self):
        body='// keep formatting and names\nwire tmp;\nassign tmp = a;\nassign y   = tmp;\n'
        d,n=inline_design('input wire a;\noutput wire y;\n'+body)
        code=d.verilog();self.assertIn(body,code)
        self.assertNotIn('generate',code);self.assertNotIn('inline_processing_',code)
        self.assertNotIn('assign a = a;',code);self.assertNotIn('assign y = y;',code)
        self.assertEqual(code.count('wire a'),1);self.assertEqual(code.count('wire y'),1)
        self.compile(code)

    def test_simple_alias_when_names_differ(self):
        d,n=inline_design('input wire a; output reg y; always @* y=~a;')
        for top in d.nodes[1:]:
            old=top.name;top.name='external_'+old;top.ports()[0].name=top.name
            for w in d.wires:
                for attr in ('source','target'):
                    ep=getattr(w,attr)
                    if ep and ep[0]==top.id:setattr(w,attr,(top.id,top.name))
        code=d.verilog();self.assertIn('wire a;',code);self.assertIn('reg y;',code)
        self.assertIn('assign a = external_a;',code);self.assertIn('assign external_y = y;',code)
        self.assertNotIn('inline_processing_',code);self.compile(code)

    def test_existing_declared_signal_is_reused(self):
        d,n=inline_design('input wire a; output reg y; always @* y=~a;',declarations='reg y;')
        out=d.nodes[-1];out.name='result';out.inputs[0].name='result'
        d.wires[-1].target=(out.id,'result');d.label_wire(d.wires[-1].id,'y')
        code=d.verilog();self.assertEqual(code.count('reg y;'),1);self.assertNotIn('wire y;',code)
        self.assertNotIn('assign y = y;',code);self.compile(code)
        d.declarations='wire y;'
        with self.assertRaisesRegex(DesignError,'must be declared'):d.verilog()

    def test_inline_names_used_for_unnamed_internal_net(self):
        n=Node(kind='inline',name='producer');update_interface(n,'output reg ready; initial ready=0;')
        sink=Node(module='sink',name='u_sink',inputs=[Port('enable')],outputs=[])
        d=Document(nodes=[n,sink]);d.connect((n.id,'ready'),(sink.id,'enable'))
        code=d.verilog();self.assertEqual(code.count('reg ready;'),1)
        self.assertIn('.enable(ready)',code);self.assertNotIn('syn_net_',code)
        self.compile(code+'\nmodule sink(input wire enable); endmodule\n')

    def test_shared_input_declared_once_across_blocks(self):
        source=Node(kind='input',name='clock',inputs=[],outputs=[Port('clock')]);source.normalize()
        nodes=[]
        for name in ('first','second'):
            n=Node(kind='inline',name=name);update_interface(n,'input wire clk;\n// shared clock\n');nodes.append(n)
        d=Document(nodes=[source,*nodes])
        for n in nodes:d.connect((source.id,'clock'),(n.id,'clk'))
        code=d.verilog();self.assertEqual(code.count('wire clk;'),1);self.assertEqual(code.count('assign clk = clock;'),1);self.compile(code)

if __name__=='__main__':unittest.main()
