// Import this file and select sv_pipeline. No external includes are needed.
module sv_pipeline #(
    parameter int unsigned WIDTH = 8,
    parameter int unsigned LANES = 2,
    parameter string LABEL = "pipeline"
) (
    input  logic clk,
    input  logic rst_n,
    input  logic signed [LANES-1:0][WIDTH-1:0] data_in,
    output logic signed [LANES-1:0][WIDTH-1:0] data_out
);
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) data_out <= '0;
        else        data_out <= data_in;
    end
endmodule

// A second module demonstrates the module selector and unpacked array ports.
module sv_array_passthrough #(
    parameter int unsigned WIDTH = 8,
    parameter int unsigned DEPTH = 4
) (
    input  logic [WIDTH-1:0] data_in  [0:DEPTH-1],
    output logic [WIDTH-1:0] data_out [0:DEPTH-1]
);
    assign data_out = data_in;
endmodule
