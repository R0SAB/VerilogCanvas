import tempfile
import unittest
from pathlib import Path
from model import DesignError, Document, Node, Port
from hdl_import import modules_from_text,load_modules


def node(source,index=0):
    return modules_from_text(source)[index].to_node()


def wrapper(n):
    d=Document('import_test_top',nodes=[n],language='systemverilog')
    for p in n.inputs+n.outputs:
        import copy
        port=copy.deepcopy(p)
        bounds=port.packed_bounds(n.params); unpacked=port.array_bounds(n.params)
        port.span=f'{bounds[0][0]}:{bounds[0][1]}' if bounds else ''
        port.packed_extra=[f'{a}:{b}' for a,b in bounds[1:]]
        port.unpacked=[f'{a}:{b}' for a,b in unpacked]
        kind='input' if p in n.inputs else 'output'
        top=Node(kind=kind,name=p.name,inputs=[port] if kind=='output' else [],outputs=[port] if kind=='input' else [])
        top.normalize(); d.nodes.append(top)
        if kind=='input': d.connect((top.id,p.name),(n.id,p.name))
        else: d.connect((n.id,p.name),(top.id,p.name))
    return d

class ImportTests(unittest.TestCase):
    def test_ansi_inheritance_signed(self):
        n=node('module foo #(parameter integer W=8, D=2) (input clk, input logic signed [W-1:0] a,b, output logic [W-1:0] y); endmodule')
        self.assertEqual(n.module,'foo'); self.assertEqual(n.params,{'W':'8','D':'2'})
        self.assertEqual([p.name for p in n.inputs],['clk','a','b'])
        self.assertTrue(n.inputs[1].signed); self.assertTrue(n.inputs[2].signed)
        self.assertFalse(n.outputs[0].signed); self.assertEqual(n.inputs[2].width(n.params),8)

    def test_non_ansi(self):
        n=node('module legacy(a, b, q); parameter W=8; input [W-1:0] a,b; output [W-1:0] q; reg [W-1:0] q; endmodule')
        self.assertEqual([p.name for p in n.inputs],['a','b']); self.assertEqual(n.outputs[0].width(n.params),8)

    def test_body_parameter_and_localparam(self):
        n=node('module foo(a,q); parameter W=8; localparam L=W-1; input [L:0] a; output [L:0] q; endmodule')
        self.assertEqual(n.inputs[0].width(n.params),8); self.assertNotIn('L',n.params)
        n.params['W']='16'; self.assertEqual(n.inputs[0].width(n.params),16)
        self.assertNotIn('.L(',wrapper(n).verilog())

    def test_header_localparam(self):
        n=node('module foo #(parameter int W=8, localparam int HI=W-1) (input [HI:0] a, output [HI:0] q); endmodule')
        self.assertEqual(n.inputs[0].width(n.params),8); self.assertEqual(set(n.params),{'W'})

    def test_port_initializers_ansi(self):
        n=node("module foo(input logic en = 1'b1, output reg [7:0] a = 0, b = {4'hf,4'h0}, output logic flag = config.reset); endmodule")
        self.assertEqual([p.name for p in n.inputs],['en'])
        self.assertEqual([p.name for p in n.outputs],['a','b','flag'])
        self.assertEqual([p.width(n.params) for p in n.outputs],[8,8,1])
        self.assertEqual(n.params,{})

    def test_port_initializers_nonansi(self):
        n=node("module foo(a,b); output reg signed [15:0] a = 0, b = choose(1,2); endmodule")
        self.assertEqual([p.name for p in n.outputs],['a','b'])
        self.assertTrue(all(p.signed and p.width(n.params)==16 for p in n.outputs))

    def test_port_initializer_macro_is_not_an_interface_dependency(self):
        n=node("module foo #(parameter W=8)(output logic [W-1:0] a = `INITIAL_DATA); endmodule")
        self.assertEqual(n.outputs[0].width(n.params),8)
        self.assertEqual(n.params,{'W':'8'})

    def test_defaults_nested_commas(self):
        n=node('module foo #(parameter W=8, parameter MASK={2{4\'ha}}, parameter string S="hello, world", parameter real R=1.25) (); endmodule')
        self.assertEqual(n.params['S'],'"hello, world"'); self.assertEqual(n.params['R'],'1.25')
        self.assertIn("4'ha",n.params['MASK'])

    def test_ignore_comments_strings_attributes_functions(self):
        n=node('''// module ghost(input x); endmodule
        (* keep_hierarchy = "yes" *) module foo(input a, output q);
        /* input wrong; parameter BAD = 1; */
        function automatic integer f(input internal_arg);
            integer internal_var; begin f=1; end
        endfunction
        task t; input bad; endtask
        initial begin $display("module wrong(input x); endmodule"); end
        always @(*) begin end
        endmodule''')
        self.assertEqual([p.name for p in n.inputs],['a']); self.assertEqual(n.params,{})

    def test_multiple_modules_select_only(self):
        modules=modules_from_text('module unsupported(bus_if.master bus); endmodule module good(input a); endmodule')
        self.assertEqual([m.name for m in modules],['unsupported','good'])
        self.assertEqual(modules[1].to_node().inputs[0].name,'a')
        with self.assertRaises(DesignError): modules[0].to_node()

    def test_arrays_and_integer_types(self):
        n=node('module foo #(parameter N=2) (input bit flag, input int signed count, input logic [N-1:0][7:0] data [0:N-1], output logic [N-1:0][7:0] q [N]); endmodule')
        self.assertTrue(n.inputs[0].two_state); self.assertEqual(n.inputs[1].width({}),32)
        self.assertTrue(n.inputs[1].signed); self.assertEqual(n.inputs[2].width(n.params),32)
        self.assertEqual(n.inputs[2].array_bounds(n.params),[(0,1)])
        self.assertEqual(n.outputs[0].array_bounds(n.params),[(0,1)])

    def test_unsupported_rejected(self):
        headers=['inout wire a','ref logic a','some_type a','iface.master bus','input my_type a','input logic a[]']
        for h in headers:
            with self.subTest(h=h), self.assertRaises(DesignError): node(f'module foo({h}); endmodule')
        for body in ['parameter type T=int','parameter int A[2]=\'{1,2}','parameter W=`WIDTH']:
            with self.subTest(body=body),self.assertRaises(DesignError): node(f'module foo #({body})(); endmodule')

    def test_preprocessor_rejected(self):
        with self.assertRaises(DesignError): node('`ifdef USE_A\n module foo(input a); endmodule\n`endif')
        with self.assertRaises(DesignError): node('module foo(input [`WIDTH-1:0] a); endmodule')

    def test_timescale_allowed(self):
        n=node('`timescale 1ns/1ps\n`default_nettype none\nmodule foo(input a); endmodule\n`default_nettype wire')
        self.assertEqual(n.inputs[0].name,'a')

    def test_invalid_not_partial(self):
        sources=['module foo(a,b); input a; endmodule','module foo(input a, output a); endmodule','module foo(input a);', 'module foo(input a; endmodule', 'not a module', '/* unclosed']
        for source in sources:
            with self.subTest(source=source),self.assertRaises(DesignError): node(source)

    def test_no_ports(self):
        self.assertEqual(node('module foo; endmodule').ports(),[])
        self.assertEqual(node('module foo #() (); endmodule').ports(),[])

    def test_internal_opaque_localparams_do_not_block(self):
        n=node("module foo(input a, output q); typedef enum logic {S0,S1} state_t; localparam state_t START=S0; localparam int LUT[2]='{1,2}; assign q=a; endmodule")
        self.assertEqual(n.params,{})
        self.assertEqual([p.name for p in n.ports()],['a','q'])

    def test_numeric_underscores_and_string_punctuation(self):
        n=node('module foo #(parameter W=1_024, parameter string S="http://host/a;b") (input [W-1:0] a); endmodule')
        self.assertEqual(n.inputs[0].width(n.params),1024)
        self.assertEqual(n.params['S'],'"http://host/a;b"')

    def test_cp1251_file(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'module.v'; p.write_bytes('// Русский комментарий\nmodule foo(input a); endmodule'.encode('cp1251'))
            self.assertEqual(load_modules(p)[0].to_node().module,'foo')

    def test_module_lifetime_end_label(self):
        n=node('module automatic foo(input logic a); endmodule : foo')
        self.assertEqual(n.module,'foo')

class SystemVerilogTests(unittest.TestCase):
    def test_export_modes(self):
        d=wrapper(node('module foo(input signed [7:0] a, output signed [7:0] q); endmodule'))
        self.assertIn('input logic signed [7:0] a',d.verilog())
        self.assertIn('.a(a)',d.verilog());self.assertNotIn('syn_net_',d.verilog())
        self.assertIn('input wire signed [7:0] a',d.verilog('verilog'))

    def test_array_export_and_guard(self):
        d=wrapper(node('module foo(input logic [1:0][7:0] a [0:3], output logic [1:0][7:0] q [0:3]); endmodule'))
        self.assertIn('input logic [1:0][7:0] a [0:3]',d.verilog())
        self.assertIn('.q(q)',d.verilog());self.assertNotIn('syn_net_',d.verilog())
        with self.assertRaises(DesignError): d.verilog('verilog')

    def test_shape_mismatch(self):
        n=node('module foo(input [7:0] a [0:1], output [15:0] q); endmodule')
        d=Document(nodes=[n],language='systemverilog')
        with self.assertRaises(DesignError): d.connect((n.id,'q'),(n.id,'a'))

    def test_two_state(self):
        d=wrapper(node('module foo(input bit a, output bit q); endmodule'))
        self.assertIn('input bit a',d.verilog()); self.assertIn('.a(a)',d.verilog())

    def test_v2_roundtrip(self):
        d=wrapper(node('module foo(input bit signed [3:0][7:0] a [0:1]); endmodule'))
        restored=Document.deserialize(d.serialize())
        self.assertEqual(restored.language,'systemverilog'); self.assertEqual(d.verilog(),restored.verilog())

    def test_old_v1_file(self):
        d=Document.load(Path(__file__).resolve().parent.parent/'examples'/'demo.vsch')
        self.assertEqual(d.language,'verilog'); self.assertIn('wire [7:0]',d.verilog())

    def test_editable_label_roundtrip(self):
        for label in ['clk','signed [7:0]data','bit [1:0][7:0]data [0:1]','logic [W-1:0]data [N]','int count']:
            p=Port.parse(label); self.assertEqual(Port.parse(p.label()),p)

if __name__=='__main__': unittest.main()
