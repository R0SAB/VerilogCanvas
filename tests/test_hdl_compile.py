"""Optional compiler checks: pip install pyslang (not needed by the app)."""
import unittest
from pathlib import Path
try:
    import pyslang
    from pyslang import ast,syntax
except ImportError:
    pyslang=None
from test_import import node,wrapper
from model import Document

@unittest.skipIf(pyslang is None,'Optional pyslang compiler is not installed')
class HDLCompileTests(unittest.TestCase):
    def check_hdl(self,source,language='systemverilog'):
        n=node(source); d=wrapper(n)
        compilation=ast.Compilation()
        compilation.addSyntaxTree(syntax.SyntaxTree.fromText(source+'\n'+d.verilog(language)))
        compilation.getRoot()
        diagnostics=compilation.getAllDiagnostics()
        errors=[x for x in diagnostics if x.isError()]
        self.assertFalse(errors,pyslang.DiagnosticEngine.reportAll(compilation.sourceManager,diagnostics))
        return diagnostics

    def test_sv_logic_typed_parameters(self):
        self.check_hdl('''module pipe #(
            parameter int unsigned W=8,
            parameter logic [7:0] MASK=8'hA5,
            parameter string MODE="SIMPLE"
        )(input logic clk, input logic signed [W-1:0] a, output logic signed [W-1:0] q);
        always_ff @(posedge clk) q <= a;
        endmodule''')

    def test_sv_packed_unpacked_arrays(self):
        self.check_hdl('module arr #(parameter int N=2)(input logic signed [N-1:0][7:0] a [0:3], output logic signed [N-1:0][7:0] q [0:3]); assign q=a; endmodule')

    def test_sv_two_state_integer(self):
        self.check_hdl('module integers(input int a, input bit b, output int q, output bit flag); assign q=a; assign flag=b; endmodule')

    def test_v_legacy(self):
        self.check_hdl('module legacy(a,q); parameter W=8; input signed [W-1:0] a; output signed [W-1:0] q; assign q=a; endmodule','verilog')

    def test_localparam_default_dependencies(self):
        self.check_hdl('module derived #(parameter int W=8, localparam int HI=W-1)(input logic [HI:0] a, output logic [HI:0] q); assign q=a; endmodule')

    def test_remote_labels_example(self):
        base=Path(__file__).resolve().parent.parent/'examples'
        d=Document.load(base/'label_demo.vsch')
        compilation=ast.Compilation()
        compilation.addSyntaxTree(syntax.SyntaxTree.fromText((base/'sv_pipeline.sv').read_text()))
        compilation.addSyntaxTree(syntax.SyntaxTree.fromText(d.verilog()))
        compilation.getRoot(); diagnostics=compilation.getAllDiagnostics()
        self.assertFalse(any(x.isError() for x in diagnostics),pyslang.DiagnosticEngine.reportAll(compilation.sourceManager,diagnostics))
        self.assertNotIn('syn_net_',d.verilog())

    def test_top_port_names_as_net_labels(self):
        source='module alias_pipe(input logic signed [7:0] a, output logic signed [7:0] q); assign q=a; endmodule'
        d=wrapper(node(source)); original=d.wires[:]; d.wires=[]
        for index,w in enumerate(original):
            a=d.connect(w.source,end=[400,index*40]);b=d.connect(w.target,end=[600,index*40])
            source_node=d.node(w.source[0]);target_node=d.node(w.target[0])
            name=source_node.name if source_node.kind=='input' else target_node.name
            first,second=(a,b) if source_node.kind=='input' else (b,a)
            d.label_wire(first.id,name);d.label_wire(second.id,name)
        compilation=ast.Compilation();compilation.addSyntaxTree(syntax.SyntaxTree.fromText(source+'\n'+d.verilog()))
        compilation.getRoot();diagnostics=compilation.getAllDiagnostics()
        self.assertFalse(any(x.isError() for x in diagnostics),pyslang.DiagnosticEngine.reportAll(compilation.sourceManager,diagnostics))

    def test_existing_example(self):
        base=Path(__file__).resolve().parent.parent/'examples'
        d=Document.load(base/'demo.vsch')
        compilation=ast.Compilation()
        for code in [(base/'data_pipe.v').read_text(),d.verilog()]:
            compilation.addSyntaxTree(syntax.SyntaxTree.fromText(code))
        compilation.getRoot(); diagnostics=compilation.getAllDiagnostics()
        self.assertFalse(any(x.isError() for x in diagnostics),pyslang.DiagnosticEngine.reportAll(compilation.sourceManager,diagnostics))

if __name__=='__main__': unittest.main()
