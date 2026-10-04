"""Extract raw HDL even when the schematic's JSON is unreadable. Standard library only."""
import argparse
import re
from pathlib import Path

BEGIN=re.compile(rb'^// ===== BEGIN HDL ([0-9a-f]{32}_\d+) (.*?) =====\r?\n',re.M)

def recover(raw):
    starts=list(BEGIN.finditer(raw));result=[]
    for i,match in enumerate(starts):
        end=re.search(rb'\r?\n// ===== END HDL '+re.escape(match[1])+rb' =====\r?\n',raw[match.end():])
        next_start=starts[i+1].start() if i+1<len(starts) else len(raw)
        complete=end is not None and match.end()+end.start()<next_start
        finish=match.end()+end.start() if complete else next_start
        result.append((match[2].decode('utf-8',errors='replace'),raw[match.end():finish],complete))
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('schematic');parser.add_argument('output_directory')
    args=parser.parse_args();records=recover(Path(args.schematic).read_bytes())
    if not records: parser.error('No raw HDL sections found')
    destination=Path(args.output_directory);destination.mkdir(parents=True,exist_ok=True)
    for i,(label,source,complete) in enumerate(records):
        path=destination/f'{i:03d}_{"recovered" if complete else "partial"}.sv'
        with path.open('xb') as file: file.write(source)
        print(f'{path}: {label}'+('' if complete else ' — incomplete section; inspect before use'))

if __name__=='__main__': main()
