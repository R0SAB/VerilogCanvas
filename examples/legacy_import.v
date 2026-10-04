// Non-ANSI Verilog interface: ports/parameters declared in the module body.
module legacy_pipeline(clk, data_in, data_out);
    parameter WIDTH = 8;
    localparam HIGH_BIT = WIDTH-1;
    input clk;
    input [HIGH_BIT:0] data_in;
    output [HIGH_BIT:0] data_out;
    reg [HIGH_BIT:0] data_out;
    always @(posedge clk) data_out <= data_in;
endmodule
