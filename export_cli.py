"""Headless exporter: python export_cli.py design.vsch output.v"""
import argparse
from pathlib import Path
from model import Document

def main():
    parser=argparse.ArgumentParser(description='Export VerilogCanvas schematic to Verilog/SystemVerilog')
    parser.add_argument('schematic'); parser.add_argument('output')
    parser.add_argument('--language',choices=['verilog','systemverilog'],help='Default: infer from .v/.sv, otherwise use schematic setting')
    args=parser.parse_args()
    language=args.language or {'.v':'verilog','.sv':'systemverilog'}.get(Path(args.output).suffix.lower())
    try: Path(args.output).write_text(Document.load(args.schematic).verilog(language),encoding='utf-8')
    except (OSError,ValueError) as exc: parser.exit(1,f'{exc}\n')

if __name__=='__main__': main()
