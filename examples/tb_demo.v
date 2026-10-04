`timescale 1ns/1ps
module tb_demo;
reg clk = 0;
reg rst_n = 1;
reg [7:0] data_in = 8'h00;
wire [7:0] data_out;
wire [7:0] monitor;
demo_top dut (
    .clk(clk), .rst_n(rst_n), .data_in(data_in),
    .data_out(data_out), .monitor(monitor)
);
always #5 clk = ~clk;
initial begin
    #1 rst_n = 0;
    #1;
    if (data_out !== 8'h00 || monitor !== 8'h00) begin
        $display("FAIL: reset"); $finish;
    end
    #1 rst_n = 1;
    data_in = 8'hA5;
    @(posedge clk); #1;
    if (data_out !== 8'hA5 || monitor !== 8'hA5) begin
        $display("FAIL: first transfer or fanout"); $finish;
    end
    data_in = 8'h3C;
    @(posedge clk); #1;
    if (data_out !== 8'h3C || monitor !== 8'h3C) begin
        $display("FAIL: second transfer or fanout"); $finish;
    end
    $display("PASS");
    $finish;
end
endmodule
