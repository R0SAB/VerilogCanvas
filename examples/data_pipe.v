module data_pipe #(
    parameter WIDTH = 8
) (
    input wire clk,
    input wire rst_n,
    input wire [WIDTH-1:0] data_in,
    output reg [WIDTH-1:0] data_out
);
always @(posedge clk or negedge rst_n) begin
    if (!rst_n)
        data_out <= {WIDTH{1'b0}};
    else
        data_out <= data_in;
end
endmodule
